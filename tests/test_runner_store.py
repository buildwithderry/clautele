import json
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from clautele.config import Config
from clautele.runner import ClaudeRun, build_args, child_env, parse_line
from clautele.store import StateStore

BASE = {"TELEGRAM_BOT_TOKEN": "123:abc", "ALLOWED_USER_IDS": "1"}


def make_cfg(tmp_path: Path, **extra):
    return Config.from_env(
        {**BASE, "CLAUDE_WORKDIR": str(tmp_path / "ws"), "DATA_DIR": str(tmp_path / "d"), **extra}
    )


def test_build_args_basic_and_resume(tmp_path):
    cfg = make_cfg(tmp_path, CLAUDE_ALLOWED_TOOLS="Read", CLAUDE_MODEL="sonnet")
    args = build_args(cfg, session_id="sid-1", permission_mode=None, model=None, extra_allowed_tools=["Bash", "Read"])
    assert args[:2] == ["claude", "-p"]
    assert args[args.index("--resume") + 1] == "sid-1"
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--allowed-tools") + 1] == "Read,Bash"  # tanpa duplikat
    assert args[args.index("--permission-prompts") + 1] == "none"


def test_build_args_overrides(tmp_path):
    cfg = make_cfg(tmp_path)
    args = build_args(cfg, session_id=None, permission_mode="plan", model="opus")
    assert "--resume" not in args
    assert args[args.index("--permission-mode") + 1] == "plan"
    assert args[args.index("--model") + 1] == "opus"


def test_child_env_strips_telegram_token():
    env = child_env({"TELEGRAM_BOT_TOKEN": "secret", "PATH": "/bin"})
    assert "TELEGRAM_BOT_TOKEN" not in env and env["PATH"] == "/bin"


def test_parse_line():
    assert parse_line('{"a": 1}') == {"a": 1}
    assert parse_line("bukan json") is None
    assert parse_line("") is None
    assert parse_line("[1,2]") is None


def test_store_roundtrip_and_reset(tmp_path):
    path = tmp_path / "s.json"
    store = StateStore(path)
    s = store.get(7)
    s.session_id, s.active, s.turns = "abc", True, 3
    store.save()

    again = StateStore(path).get(7)
    assert (again.session_id, again.active, again.turns) == ("abc", True, 3)

    store.reset_session(7)
    after = StateStore(path).get(7)
    assert after.session_id is None and after.turns == 0 and after.active is True


def test_store_ignores_unknown_fields(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"1": {"session_id": "x", "field_masa_depan": 1}}))
    assert StateStore(path).get(1).session_id == "x"


def fake_claude(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fake_claude.py"
    script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


async def test_run_parses_stream_and_result(tmp_path):
    bin_ = fake_claude(
        tmp_path,
        """
        import json, sys
        prompt = sys.stdin.read()
        out = lambda d: print(json.dumps(d), flush=True)
        out({"type": "system", "subtype": "init", "session_id": "sess-9"})
        out({"type": "assistant", "session_id": "sess-9", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}})
        out({"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-9",
             "result": "echo: " + prompt, "total_cost_usd": 0.01, "duration_ms": 5, "num_turns": 2,
             "permission_denials": [{"tool_name": "Edit"}]})
        """,
    )
    cfg = make_cfg(tmp_path, CLAUDE_BIN=bin_)
    seen = []

    async def on_event(e):
        seen.append(e["type"])

    res = await ClaudeRun(cfg, [bin_]).run("halo dunia", on_event)
    assert res.text == "echo: halo dunia"  # prompt sampai lewat stdin
    assert res.session_id == "sess-9"
    assert res.saw_result and not res.is_error
    assert res.cost_usd == pytest.approx(0.01) and res.num_turns == 2
    assert res.permission_denials == [{"tool_name": "Edit"}]
    assert seen == ["system", "assistant", "result"]


async def test_run_without_result_is_error_and_keeps_stderr(tmp_path):
    bin_ = fake_claude(
        tmp_path,
        """
        import sys
        sys.stdin.read()
        print("No conversation found with session ID", file=sys.stderr)
        sys.exit(1)
        """,
    )
    cfg = make_cfg(tmp_path)
    res = await ClaudeRun(cfg, [bin_]).run("x")
    assert res.is_error and not res.saw_result
    assert "No conversation found" in res.stderr_tail


async def test_run_timeout_kills_process(tmp_path):
    bin_ = fake_claude(tmp_path, "import time, sys\nsys.stdin.read()\ntime.sleep(60)\n")
    cfg = make_cfg(tmp_path, CLAUDE_TIMEOUT_SECONDS="1")
    res = await ClaudeRun(cfg, [bin_]).run("x")
    assert res.timed_out


async def test_run_cancel(tmp_path):
    import asyncio

    bin_ = fake_claude(tmp_path, "import time, sys\nsys.stdin.read()\ntime.sleep(60)\n")
    cfg = make_cfg(tmp_path)
    run = ClaudeRun(cfg, [bin_])
    task = asyncio.create_task(run.run("x"))
    await asyncio.sleep(0.5)
    run.cancel()
    res = await asyncio.wait_for(task, timeout=10)
    assert res.cancelled
