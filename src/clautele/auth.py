"""Login ulang Claude Code lewat Telegram (`claude auth login`).

Alurnya sama dengan login manual: CLI mencetak URL otorisasi, user membukanya di browser, lalu menempelkan
kode yang tampil di halaman. Di sini kode itu dikirim lewat chat dan diteruskan ke stdin proses `claude auth login`.
Hanya boleh dimulai saat Claude BELUM login (sesi kedaluwarsa/hilang); pemanggil wajib mengeceknya dengan `status()`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
from dataclasses import dataclass

from .config import Config
from .runner import child_env

URL_RE = re.compile(r"https://\S*oauth/authorize\S*")
URL_TIMEOUT = 25  # detik menunggu CLI mencetak URL
CODE_TIMEOUT = 45  # detik menunggu CLI menukar kode
FLOW_TTL = 600  # detik; login yang tidak diselesaikan dibatalkan otomatis


class AuthError(RuntimeError):
    pass


@dataclass
class AuthStatus:
    logged_in: bool
    expires_at: str | None = None
    method: str | None = None


async def status(cfg: Config, timeout: float = 20.0) -> AuthStatus:
    """Jalankan `claude auth status`. Gagal menjalankan/mengurai dianggap belum login."""
    try:
        proc = await asyncio.create_subprocess_exec(
            cfg.claude_bin,
            "auth",
            "status",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=child_env(),
        )
    except FileNotFoundError as exc:
        raise AuthError(f"Perintah '{cfg.claude_bin}' tidak ditemukan.") from exc
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise AuthError("`claude auth status` tidak menjawab (timeout).")
    try:
        data = json.loads(out.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return AuthStatus(False)
    if not isinstance(data, dict):
        return AuthStatus(False)
    return AuthStatus(bool(data.get("loggedIn")), data.get("loginExpiresAt"), data.get("authMethod"))


class LoginFlow:
    """Satu proses `claude auth login` yang menunggu kode dari user."""

    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._proc: asyncio.subprocess.Process | None = None
        self._buf = ""
        self._reader: asyncio.Task[None] | None = None
        self._ttl: asyncio.Task[None] | None = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> str:
        """Mulai proses dan kembalikan URL otorisasi untuk dibuka user."""
        env = child_env()
        env.pop("BROWSER", None)
        self._proc = await asyncio.create_subprocess_exec(
            self._cfg.claude_bin,
            "auth",
            "login",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        assert self._proc.stdout
        self._reader = asyncio.create_task(self._read())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + URL_TIMEOUT
        while loop.time() < deadline:
            if m := URL_RE.search(self._buf):
                self._ttl = asyncio.create_task(self._expire())
                return m.group(0)
            if not self.alive:
                break
            await asyncio.sleep(0.2)
        tail = self._buf.strip()[-300:]
        self.cancel()
        raise AuthError(f"CLI tidak memberi URL login. {tail}".strip())

    async def _read(self) -> None:
        assert self._proc and self._proc.stdout
        async for raw in self._proc.stdout:
            self._buf += raw.decode("utf-8", "replace")
        # Prompt "Paste code here >" tidak diakhiri newline; read() di atas tetap menampung sisanya.

    async def _expire(self) -> None:
        await asyncio.sleep(FLOW_TTL)
        self.cancel()

    async def submit(self, code: str) -> tuple[bool, str]:
        """Kirim kode ke CLI. Mengembalikan (berhasil, pesan)."""
        code = code.strip()
        if not self.alive or self._proc is None or self._proc.stdin is None:
            return False, "Proses login sudah berhenti. Mulai lagi dengan /claude_login."
        try:
            self._proc.stdin.write((code + "\n").encode("utf-8"))
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            return False, "Proses login sudah berhenti. Mulai lagi dengan /claude_login."
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=CODE_TIMEOUT)
        except asyncio.TimeoutError:
            self.cancel()
            return False, "Tidak ada jawaban dari server login (timeout). Mulai lagi dengan /claude_login."
        if self._reader:
            await asyncio.gather(self._reader, return_exceptions=True)
        self._cleanup_ttl()
        out = self._buf
        if "Login successful" in out:
            return True, "Login berhasil."
        m = re.search(r"Login failed:[^\n]*", out)
        return False, (m.group(0) if m else "Login gagal.")

    def _cleanup_ttl(self) -> None:
        if self._ttl and not self._ttl.done():
            self._ttl.cancel()

    def cancel(self) -> None:
        self._cleanup_ttl()
        if self._proc and self._proc.returncode is None:
            try:
                os.killpg(self._proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if self._reader and not self._reader.done():
            self._reader.cancel()


def looks_like_auth_error(*texts: str) -> bool:
    """Apakah keluaran Claude menandakan masalah login (bukan kesalahan biasa)?"""
    blob = " ".join(t for t in texts if t).lower()
    return any(
        s in blob
        for s in (
            "failed to authenticate",
            "oauth session expired",
            "not logged in",
            "please run /login",
            "invalid api key",
            "authentication_error",
        )
    )
