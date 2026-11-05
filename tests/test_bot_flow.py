"""Alur bot end-to-end dengan Telegram palsu dan `claude` palsu."""

import json
import stat
import sys
import textwrap
from types import SimpleNamespace

from clautele.bot import ClauteleBot
from clautele.config import Config
from clautele.store import StateStore


class FakeMessage:
    def __init__(self, bot, chat_id, text, markup):
        self.bot, self.chat_id, self.text, self.reply_markup = bot, chat_id, text, markup
        self.edits = []

    async def edit_text(self, text):
        self.text = text
        self.edits.append(text)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        m = FakeMessage(self, chat_id, text, reply_markup)
        self.sent.append(m)
        return m

    async def send_chat_action(self, *a, **kw):
        pass


def make(tmp_path, script_body):
    script = tmp_path / "fake_claude.py"
    script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(script_body))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    cfg = Config.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "1:x",
            "ALLOWED_USER_IDS": "5",
            "CLAUDE_BIN": str(script),
            "CLAUDE_WORKDIR": str(tmp_path / "ws"),
            "DATA_DIR": str(tmp_path / "d"),
        }
    )
    store = StateStore(tmp_path / "state.json")
    bot = ClauteleBot(cfg, store)
    ctx = SimpleNamespace(bot=FakeBot(), chat_data={}, args=[])
    return bot, ctx, store


QUESTION_CLAUDE = """
import json, sys
sys.stdin.read()
txt = 'Ada dua opsi.\\n<<ASK>>{"question": "Pilih DB?", "options": ["Postgres", "SQLite"]}<<END>>'
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
    "session_id": "S1", "result": txt, "total_cost_usd": 0.02, "num_turns": 1}), flush=True)
"""

DENIAL_CLAUDE = """
import json, sys
sys.stdin.read()
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": "S2",
    "result": "Butuh izin.", "permission_denials": [{"tool_name": "Bash"}]}), flush=True)
"""


async def test_question_becomes_buttons_and_answer_resumes(tmp_path):
    bot, ctx, store = make(tmp_path, QUESTION_CLAUDE)
    await bot.run_prompt(ctx, 1, "bantu pilih db")

    texts = [m.text for m in ctx.bot.sent]
    assert any(t.startswith("Ada dua opsi.") for t in texts)
    assert not any("<<ASK>>" in t for t in texts)  # penanda tidak bocor ke user
    ask = [m for m in ctx.bot.sent if m.reply_markup][-1]
    labels = [b.text for row in ask.reply_markup.inline_keyboard for b in row]
    assert labels == ["Postgres", "SQLite"]
    assert ctx.chat_data["pending_options"] == ["Postgres", "SQLite"]

    st = store.get(1)
    assert st.session_id == "S1" and st.turns == 1 and st.total_cost_usd > 0


async def test_permission_denial_offers_grant(tmp_path):
    bot, ctx, store = make(tmp_path, DENIAL_CLAUDE)
    await bot.run_prompt(ctx, 1, "jalankan sesuatu")
    grant = [m for m in ctx.bot.sent if m.reply_markup and "Ditolak" in m.text][-1]
    data = [b.callback_data for row in grant.reply_markup.inline_keyboard for b in row]
    assert "grant:Bash" in data
    assert ctx.chat_data["pending_grants"] == ["Bash"]


async def test_busy_chat_rejects_second_prompt(tmp_path):
    bot, ctx, _ = make(tmp_path, QUESTION_CLAUDE)
    bot.runs[1] = object()  # seolah sedang bekerja
    await bot.run_prompt(ctx, 1, "lagi")
    assert "masih bekerja" in ctx.bot.sent[-1].text


async def test_missing_binary_reports_friendly_error(tmp_path):
    bot, ctx, _ = make(tmp_path, QUESTION_CLAUDE)
    object.__setattr__(bot.cfg, "claude_bin", "/tidak/ada/claude")
    # build_args memakai cfg.claude_bin
    await bot.run_prompt(ctx, 1, "halo")
    assert any("tidak ditemukan" in m.text for m in ctx.bot.sent)
    assert 1 not in bot.runs  # state bersih setelah gagal


class FakeUpdate:
    def __init__(self, uid, chat_id=1):
        self.effective_user = SimpleNamespace(id=uid)
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.replies = []
        outer = self

        class Msg:
            text = "halo"

            async def reply_text(self, t, **kw):
                outer.replies.append(t)

            async def reply_markdown(self, t, **kw):
                outer.replies.append(t)

        self.effective_message = Msg()


async def test_unauthorized_user_blocked(tmp_path):
    bot, ctx, store = make(tmp_path, QUESTION_CLAUDE)
    upd = FakeUpdate(uid=999)
    await bot.on_text(upd, ctx)
    assert "tidak diizinkan" in upd.replies[0] and "999" in upd.replies[0]
    assert ctx.bot.sent == []  # tidak ada proses Claude yang dijalankan


async def test_start_end_session_lifecycle(tmp_path):
    bot, ctx, store = make(tmp_path, QUESTION_CLAUDE)

    inactive = FakeUpdate(5)
    await bot.on_text(inactive, ctx)
    assert "/start_claude" in inactive.replies[0] and ctx.bot.sent == []

    start = FakeUpdate(5)
    await bot.cmd_start_claude(start, ctx)
    assert store.get(1).active is True

    await bot.run_prompt(ctx, 1, "x")
    assert store.get(1).session_id == "S1"

    end = FakeUpdate(5)
    await bot.cmd_end_claude(end, ctx)
    s = store.get(1)
    assert s.active is False and s.session_id is None
