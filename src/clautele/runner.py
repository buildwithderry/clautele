"""Menjalankan `claude -p` sebagai subprocess dan mengurai stream-json-nya."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .config import Config

# Variabel yang tidak boleh bocor ke proses Claude (yang bisa menjalankan Bash).
SECRET_ENV_KEYS = ("TELEGRAM_BOT_TOKEN",)

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class RunResult:
    text: str = ""
    session_id: str | None = None
    is_error: bool = False
    cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    permission_denials: list[Any] = field(default_factory=list)
    stderr_tail: str = ""
    cancelled: bool = False
    timed_out: bool = False
    saw_result: bool = False


def build_args(
    cfg: Config,
    *,
    session_id: str | None,
    permission_mode: str | None,
    model: str | None,
    extra_allowed_tools: tuple[str, ...] | list[str] = (),
) -> list[str]:
    """Susun argumen CLI. Prompt dikirim lewat stdin, bukan argv."""
    args = [
        cfg.claude_bin,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-prompts",
        "none",  # tidak ada TTY: apa pun yang butuh izin ditolak, bukan menggantung
        "--permission-mode",
        permission_mode or cfg.permission_mode,
    ]
    if session_id:
        args += ["--resume", session_id]
    chosen_model = model or cfg.model
    if chosen_model:
        args += ["--model", chosen_model]
    tools = list(dict.fromkeys([*cfg.allowed_tools, *extra_allowed_tools]))
    if tools:
        args += ["--allowed-tools", ",".join(tools)]
    if cfg.append_system_prompt:
        args += ["--append-system-prompt", cfg.append_system_prompt]
    if cfg.max_budget_usd is not None:
        args += ["--max-budget-usd", str(cfg.max_budget_usd)]
    args += list(cfg.extra_args)
    return args


def child_env(parent: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if parent is None else parent)
    for key in SECRET_ENV_KEYS:
        env.pop(key, None)
    return env


def parse_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def assistant_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    if event.get("type") != "assistant":
        return []
    content = (event.get("message") or {}).get("content") or []
    return [b for b in content if isinstance(b, dict)]


class ClaudeRun:
    """Satu eksekusi `claude -p`. Bisa dibatalkan dari luar lewat cancel()."""

    def __init__(self, cfg: Config, args: list[str]):
        self._cfg = cfg
        self._args = args
        self._proc: asyncio.subprocess.Process | None = None
        self._cancelled = False

    async def run(self, prompt: str, on_event: EventCallback | None = None) -> RunResult:
        result = RunResult()
        self._cfg.workdir.mkdir(parents=True, exist_ok=True)
        stderr_buf: deque[str] = deque(maxlen=40)
        last_text = ""

        self._proc = await asyncio.create_subprocess_exec(
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._cfg.workdir),
            env=child_env(),
            start_new_session=True,  # grup proses sendiri agar cancel membunuh anak-anaknya juga
            limit=16 * 1024 * 1024,  # event stream-json bisa besar
        )
        proc = self._proc
        assert proc.stdin and proc.stdout and proc.stderr

        async def feed() -> None:
            try:
                proc.stdin.write(prompt.encode("utf-8"))
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

        async def drain_stderr() -> None:
            async for raw in proc.stderr:
                stderr_buf.append(raw.decode("utf-8", "replace").rstrip())

        async def read_stdout() -> None:
            nonlocal last_text
            async for raw in proc.stdout:
                event = parse_line(raw.decode("utf-8", "replace"))
                if event is None:
                    continue
                if sid := event.get("session_id"):
                    result.session_id = sid
                for block in assistant_blocks(event):
                    if block.get("type") == "text" and block.get("text"):
                        last_text = block["text"]
                if event.get("type") == "result":
                    result.saw_result = True
                    result.text = event.get("result") or last_text
                    result.is_error = bool(event.get("is_error"))
                    result.cost_usd = float(event.get("total_cost_usd") or 0.0)
                    result.duration_ms = int(event.get("duration_ms") or 0)
                    result.num_turns = int(event.get("num_turns") or 0)
                    result.permission_denials = list(event.get("permission_denials") or [])
                if on_event is not None:
                    await on_event(event)

        tasks = [
            asyncio.create_task(feed()),
            asyncio.create_task(drain_stderr()),
            asyncio.create_task(read_stdout()),
        ]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=self._cfg.timeout_seconds)
            await proc.wait()
        except asyncio.TimeoutError:
            result.timed_out = True
            self._kill()
            await proc.wait()
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        result.cancelled = self._cancelled
        result.stderr_tail = "\n".join(stderr_buf)
        if not result.saw_result:
            result.is_error = True
            if not result.text:
                result.text = last_text
        return result

    def _kill(self, sig: int = signal.SIGTERM) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                os.killpg(self._proc.pid, sig)
            except ProcessLookupError:
                pass

    def cancel(self) -> None:
        self._cancelled = True
        self._kill()
