"""Alur bot end-to-end dengan Telegram palsu dan `claude` palsu."""

import json
import stat
import time
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

    async def send_photo(self, chat_id, fh, caption=None, **kw):
        self.sent.append(SimpleNamespace(kind="photo", data=fh.read(), caption=caption, text=f"[foto] {caption}", reply_markup=None))

    async def send_document(self, chat_id, fh, filename=None, caption=None, **kw):
        self.sent.append(SimpleNamespace(kind="doc", data=fh.read(), filename=filename, caption=caption, text=f"[dokumen] {filename}", reply_markup=None))


def make(tmp_path, script_body, extra_env=None):
    script = tmp_path / "fake_claude.py"
    script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(script_body))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    cfg = Config.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "1:x",
            "CLAUTELE_SANDBOX": "docker",
            **(extra_env or {}),
            "ALLOWED_USER_IDS": "5",
            "CLAUDE_BIN": str(script),
            "CLAUDE_WORKDIR": str(tmp_path / "ws"),
            "DATA_DIR": str(tmp_path / "d"),
        }
    )
    store = StateStore(tmp_path / "state.json")
    bot = ClauteleBot(cfg, store)
    ctx = SimpleNamespace(bot=FakeBot(), chat_data={}, bot_data={}, args=[])
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
        self.deleted = False
        outer = self

        class Msg:
            text = "halo"

            async def reply_text(self, t, **kw):
                outer.replies.append(t)

            async def reply_markdown(self, t, **kw):
                outer.replies.append(t)

            async def delete(self):
                outer.deleted = True

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


# ---------- 2FA ----------

from clautele.totp import code_at  # noqa: E402

TOTP = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def _now_code(offset=0):
    return code_at(TOTP, int(time.time() // 30) + offset)


class FakeUpdateArgs(FakeUpdate):
    pass


async def test_locked_until_login_then_unlocked(tmp_path):
    bot, ctx, store = make(tmp_path, QUESTION_CLAUDE, {"TOTP_SECRET": TOTP})

    locked = FakeUpdate(5)
    await bot.cmd_start_claude(locked, ctx)
    assert "Terkunci" in locked.replies[0] and not store.get(1).active

    txt = FakeUpdate(5)
    await bot.on_text(txt, ctx)
    assert "Terkunci" in txt.replies[0] and ctx.bot.sent == []  # tidak ada proses Claude

    ctx.args = ["000000"]
    bad = FakeUpdate(5)
    await bot.cmd_login(bad, ctx)
    assert "❌" in ctx.bot.sent[-1].text

    ctx.args = [_now_code()]
    good = FakeUpdate(5)
    await bot.cmd_login(good, ctx)
    assert "🔓" in ctx.bot.sent[-1].text
    assert good.deleted  # pesan berisi kode dihapus

    ok = FakeUpdate(5)
    await bot.cmd_start_claude(ok, ctx)
    assert store.get(1).active is True

    out = FakeUpdate(5)
    await bot.cmd_logout(out, ctx)
    again = FakeUpdate(5)
    await bot.cmd_status(again, ctx)
    assert "Terkunci" in again.replies[0]


async def test_login_unlisted_user_still_denied(tmp_path):
    bot, ctx, _ = make(tmp_path, QUESTION_CLAUDE, {"TOTP_SECRET": TOTP})
    ctx.args = [_now_code()]
    upd = FakeUpdate(999)
    await bot.cmd_login(upd, ctx)
    assert "tidak diizinkan" in upd.replies[0]


# ---------- file keluar / masuk ----------

FILE_CLAUDE = """
import json, sys, os
sys.stdin.read()
os.makedirs(".clautele/outbox", exist_ok=True)
open(".clautele/outbox/laporan.pdf", "wb").write(b"%PDF-isi")
open(".clautele/outbox/logo.png", "wb").write(b"PNGDATA")
open(".env", "w").write("TOKEN=rahasia")
txt = ('Ini filenya.\\n'
       '<<FILE>>{"path": ".clautele/outbox/laporan.pdf", "caption": "Laporan"}<<END>>\\n'
       '<<FILE>>{"path": ".clautele/outbox/logo.png"}<<END>>\\n'
       '<<FILE>>{"path": ".env"}<<END>>\\n'
       '<<FILE>>{"path": "/etc/hostname"}<<END>>')
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
    "session_id": "F1", "result": txt}), flush=True)
"""


async def test_files_sent_and_secrets_refused(tmp_path):
    bot, ctx, _ = make(tmp_path, FILE_CLAUDE)
    await bot.run_prompt(ctx, 1, "kirim laporan")
    sent = ctx.bot.sent
    docs = [m for m in sent if getattr(m, "kind", "") == "doc"]
    photos = [m for m in sent if getattr(m, "kind", "") == "photo"]
    assert [d.filename for d in docs] == ["laporan.pdf"] and docs[0].caption == "Laporan"
    assert docs[0].data == b"%PDF-isi"
    assert len(photos) == 1 and photos[0].data == b"PNGDATA"
    texts = " ".join(m.text for m in sent)
    assert "<<FILE>>" not in texts  # penanda tidak bocor
    assert "Tidak mengirim .env" in texts and "Tidak mengirim hostname" in texts
    assert "TOKEN=rahasia" not in texts and not any(getattr(m, "data", b"") == b"TOKEN=rahasia" for m in sent)


async def test_file_outside_outbox_refused_by_default(tmp_path):
    bot, ctx, _ = make(tmp_path, FILE_CLAUDE)
    (bot.cfg.workdir).mkdir(parents=True, exist_ok=True)
    (bot.cfg.workdir / "catatan.txt").write_text("biasa")
    refs = [type("R", (), {"path": "catatan.txt", "caption": ""})()]
    await bot._send_files(ctx, 1, refs)
    assert "di luar folder" in ctx.bot.sent[-1].text  # bukan di outbox


async def test_send_files_disabled(tmp_path):
    bot, ctx, _ = make(tmp_path, FILE_CLAUDE, {"SEND_FILES": "false"})
    await bot.run_prompt(ctx, 1, "kirim")
    assert not any(getattr(m, "kind", "") in ("doc", "photo") for m in ctx.bot.sent)
    assert any("SEND_FILES=false" in m.text for m in ctx.bot.sent)


ECHO_CLAUDE = """
import json, sys
prompt = sys.stdin.read()
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
    "session_id": "E1", "result": "PROMPT:" + prompt}), flush=True)
"""


class FakeTgFile:
    def __init__(self, payload):
        self.payload = payload

    async def download_to_drive(self, custom_path):
        from pathlib import Path

        Path(custom_path).write_bytes(self.payload)


class FakeAttachment:
    def __init__(self, payload=b"data", size=None, file_name=None):
        self.payload, self.file_size, self.file_name = payload, size or len(payload), file_name

    async def get_file(self):
        return FakeTgFile(self.payload)


class FileUpdate(FakeUpdate):
    def __init__(self, uid, **fields):
        super().__init__(uid)
        self.effective_message.photo = fields.get("photo")
        self.effective_message.document = fields.get("document")
        for k in ("voice", "audio", "video", "video_note"):
            setattr(self.effective_message, k, fields.get(k))
        self.effective_message.caption = fields.get("caption")
        self.effective_message.media_group_id = fields.get("group")


async def _active(bot, ctx):
    await bot.cmd_start_claude(FakeUpdate(5), ctx)


async def test_incoming_photo_saved_and_forwarded(tmp_path):
    bot, ctx, store = make(tmp_path, ECHO_CLAUDE)
    await _active(bot, ctx)
    upd = FileUpdate(5, photo=[FakeAttachment(b"kecil"), FakeAttachment(b"JPEGBYTES")], caption="ini apa?")
    await bot.on_file(upd, ctx)

    saved = list((bot.cfg.inbox_dir).glob("*"))
    assert len(saved) == 1 and saved[0].read_bytes() == b"JPEGBYTES"  # ukuran terbesar dipilih
    final = [m.text for m in ctx.bot.sent if m.text.startswith("PROMPT:")][0]
    assert str(saved[0]) in final and "ini apa?" in final


async def test_incoming_document_name_sanitized(tmp_path):
    bot, ctx, _ = make(tmp_path, ECHO_CLAUDE)
    await _active(bot, ctx)
    doc = FakeAttachment(b"%PDF", file_name="../../etc/laporan akhir.pdf")
    await bot.on_file(FileUpdate(5, document=doc), ctx)
    saved = list(bot.cfg.inbox_dir.glob("*"))
    assert len(saved) == 1 and saved[0].parent == bot.cfg.inbox_dir  # tidak keluar dari inbox
    assert saved[0].name.endswith("laporan_akhir.pdf")


async def test_incoming_file_too_large_rejected(tmp_path):
    bot, ctx, _ = make(tmp_path, ECHO_CLAUDE, {"UPLOAD_MAX_MB": "1"})
    await _active(bot, ctx)
    upd = FileUpdate(5, document=FakeAttachment(b"x", size=5 * 1024 * 1024, file_name="b.bin"))
    await bot.on_file(upd, ctx)
    assert "terlalu besar" in upd.replies[0]
    assert not list(bot.cfg.inbox_dir.glob("*")) if bot.cfg.inbox_dir.exists() else True


async def test_incoming_file_requires_active_session_and_auth(tmp_path):
    bot, ctx, _ = make(tmp_path, ECHO_CLAUDE)
    inactive = FileUpdate(5, document=FakeAttachment(b"x", file_name="a.txt"))
    await bot.on_file(inactive, ctx)
    assert "/start_claude" in inactive.replies[0]
    stranger = FileUpdate(999, document=FakeAttachment(b"x", file_name="a.txt"))
    await bot.on_file(stranger, ctx)
    assert "tidak diizinkan" in stranger.replies[0]
    assert not bot.cfg.inbox_dir.exists()


async def test_album_batched_into_single_prompt(tmp_path, monkeypatch):
    import asyncio

    bot, ctx, _ = make(tmp_path, ECHO_CLAUDE)
    await _active(bot, ctx)
    real_sleep = asyncio.sleep
    monkeypatch.setattr("clautele.bot.asyncio.sleep", lambda s: real_sleep(0.05))
    for i in range(3):
        await bot.on_file(
            FileUpdate(5, photo=[FakeAttachment(f"p{i}".encode())], group="G1", caption="bandingkan" if i == 0 else None),
            ctx,
        )
    await real_sleep(0.6)
    finals = [m.text for m in ctx.bot.sent if m.text.startswith("PROMPT:")]
    assert len(finals) == 1  # satu giliran untuk seluruh album
    assert finals[0].count("(foto)") == 3 and "bandingkan" in finals[0]
