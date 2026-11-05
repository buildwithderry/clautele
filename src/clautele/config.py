"""Konfigurasi dari environment variable (.env)."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

VALID_MODES = ("plan", "acceptEdits", "auto", "dontAsk", "bypassPermissions")


class ConfigError(RuntimeError):
    pass


def load_dotenv(path: Path, env: dict[str, str] | None = None) -> int:
    """Baca file .env sederhana (KEY=VALUE per baris) ke environment.

    Nilai yang sudah ada di environment tidak ditimpa, jadi `docker compose` dan
    systemd tetap menang. Mendukung nilai berspasi tanpa tanda kutip; kutip yang
    membungkus seluruh nilai dibuang. Mengembalikan jumlah variabel yang dimuat.
    """
    target = os.environ if env is None else env
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return 0
    loaded = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in target:
            target[key] = value
            loaded += 1
    return loaded


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_list(value: str | None) -> frozenset[int]:
    out: set[int] = set()
    for part in (value or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError as exc:
            raise ConfigError(f"ALLOWED_USER_IDS berisi nilai bukan angka: {part!r}") from exc
    return frozenset(out)


@dataclass(frozen=True)
class Config:
    telegram_token: str
    allowed_user_ids: frozenset[int]
    workdir: Path
    data_dir: Path
    claude_bin: str = "claude"
    permission_mode: str = "acceptEdits"
    allow_bypass: bool = False
    allowed_tools: tuple[str, ...] = ()
    model: str | None = None
    append_system_prompt: str | None = None
    max_budget_usd: float | None = None
    timeout_seconds: int = 900
    stream_progress: bool = True
    show_tool_output: bool = False
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        e = dict(os.environ if env is None else env)

        token = e.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ConfigError("TELEGRAM_BOT_TOKEN wajib diisi (ambil dari @BotFather).")

        allowed = _int_list(e.get("ALLOWED_USER_IDS"))
        if not allowed:
            raise ConfigError(
                "ALLOWED_USER_IDS wajib diisi. Bot ini mengendalikan shell di server Anda, "
                "jadi tidak boleh terbuka untuk umum. Cari ID Anda lewat @userinfobot."
            )

        mode = e.get("CLAUDE_PERMISSION_MODE", "acceptEdits").strip() or "acceptEdits"
        if mode not in VALID_MODES:
            raise ConfigError(f"CLAUDE_PERMISSION_MODE harus salah satu dari {VALID_MODES}.")
        allow_bypass = _bool(e.get("ALLOW_BYPASS_PERMISSIONS"))
        if mode == "bypassPermissions" and not allow_bypass:
            raise ConfigError(
                "bypassPermissions butuh ALLOW_BYPASS_PERMISSIONS=true sebagai konfirmasi eksplisit."
            )

        budget_raw = e.get("CLAUDE_MAX_BUDGET_USD", "").strip()
        try:
            budget = float(budget_raw) if budget_raw else None
        except ValueError as exc:
            raise ConfigError("CLAUDE_MAX_BUDGET_USD harus angka, mis. 1.5") from exc

        try:
            timeout = int(e.get("CLAUDE_TIMEOUT_SECONDS", "900") or "900")
        except ValueError as exc:
            raise ConfigError("CLAUDE_TIMEOUT_SECONDS harus bilangan bulat.") from exc

        return cls(
            telegram_token=token,
            allowed_user_ids=allowed,
            workdir=Path(e.get("CLAUDE_WORKDIR", "./workspace")).expanduser().resolve(),
            data_dir=Path(e.get("DATA_DIR", "./data")).expanduser().resolve(),
            claude_bin=e.get("CLAUDE_BIN", "claude").strip() or "claude",
            permission_mode=mode,
            allow_bypass=allow_bypass,
            allowed_tools=tuple(shlex.split(e.get("CLAUDE_ALLOWED_TOOLS", ""))),
            model=(e.get("CLAUDE_MODEL", "").strip() or None),
            append_system_prompt=(e.get("CLAUDE_APPEND_SYSTEM_PROMPT", "").strip() or None),
            max_budget_usd=budget,
            timeout_seconds=timeout,
            stream_progress=_bool(e.get("STREAM_PROGRESS"), True),
            show_tool_output=_bool(e.get("SHOW_TOOL_OUTPUT"), False),
            extra_args=tuple(shlex.split(e.get("CLAUDE_EXTRA_ARGS", ""))),
        )
