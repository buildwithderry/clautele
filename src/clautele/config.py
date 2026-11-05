"""Konfigurasi dari environment variable (.env)."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from .totp import TotpError, validate_secret
from .tts import TtsConfig, TtsError

VALID_MODES = ("plan", "acceptEdits", "auto", "dontAsk", "bypassPermissions")


class ConfigError(RuntimeError):
    pass


def load_dotenv(path: Path, env: dict[str, str] | None = None) -> int:
    """Baca file .env sederhana (KEY=VALUE per baris) ke environment.

    Nilai yang sudah ada di environment tidak ditimpa, jadi `docker compose` dan
    systemd tetap menang. Kunci duplikat di dalam berkas: yang terakhir menang, seperti docker compose. Mendukung nilai berspasi tanpa tanda kutip; kutip yang
    membungkus seluruh nilai dibuang. Mengembalikan jumlah variabel yang dimuat.
    """
    target = os.environ if env is None else env
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return 0
    parsed: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            parsed[key] = value  # kunci duplikat: yang TERAKHIR menang (sama dengan docker compose)
    loaded = 0
    for key, value in parsed.items():
        if key not in target:
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
    totp_secret: str | None = None
    totp_session_minutes: int = 60
    sandboxed: bool = False  # True di image Docker (CLAUTELE_SANDBOX=docker)
    send_files: bool = True
    send_roots: tuple[Path, ...] = ()
    send_max_mb: int = 50
    upload_max_mb: int = 20
    tts: TtsConfig | None = None

    @property
    def outbox_dir(self) -> Path:
        return self.workdir / ".clautele" / "outbox"

    @property
    def inbox_dir(self) -> Path:
        return self.workdir / ".clautele" / "inbox"
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

        # 2FA: wajib di luar sandbox Docker (mode host = akses penuh), opsional di Docker.
        sandboxed = e.get("CLAUTELE_SANDBOX", "").strip().lower() == "docker"
        totp_secret = e.get("TOTP_SECRET", "").strip() or None
        if totp_secret:
            try:
                validate_secret(totp_secret)
            except TotpError as exc:
                raise ConfigError(str(exc)) from exc
        elif not sandboxed:
            raise ConfigError(
                "Mode host (tanpa Docker) WAJIB memakai 2FA karena Claude punya akses penuh. "
                "Buat secret dengan:  python -m clautele.totp   lalu isi TOTP_SECRET di .env."
            )
        try:
            session_minutes = int(e.get("TOTP_SESSION_MINUTES", "60") or "60")
        except ValueError as exc:
            raise ConfigError("TOTP_SESSION_MINUTES harus bilangan bulat.") from exc
        if not 1 <= session_minutes <= 1440:
            raise ConfigError("TOTP_SESSION_MINUTES harus antara 1 dan 1440.")

        workdir = Path(e.get("CLAUDE_WORKDIR", "./workspace")).expanduser().resolve()
        roots_raw = [r.strip() for r in e.get("SEND_ROOTS", "").replace(";", ",").split(",") if r.strip()]
        send_roots = tuple(Path(r).expanduser().resolve() for r in roots_raw) or (workdir / ".clautele" / "outbox",)
        try:
            send_max_mb = int(e.get("SEND_MAX_MB", "50") or "50")
            upload_max_mb = int(e.get("UPLOAD_MAX_MB", "20") or "20")
        except ValueError as exc:
            raise ConfigError("SEND_MAX_MB dan UPLOAD_MAX_MB harus bilangan bulat.") from exc
        if not 1 <= send_max_mb <= 50:
            raise ConfigError("SEND_MAX_MB harus 1-50 (batas upload bot Telegram 50 MB).")
        if not 1 <= upload_max_mb <= 20:
            raise ConfigError("UPLOAD_MAX_MB harus 1-20 (batas unduh bot Telegram 20 MB).")

        try:
            tts = TtsConfig.from_env(e)
        except TtsError as exc:
            raise ConfigError(f"konfigurasi TTS salah: {exc}") from exc

        return cls(
            telegram_token=token,
            allowed_user_ids=allowed,
            workdir=workdir,
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
            totp_secret=totp_secret,
            totp_session_minutes=session_minutes,
            sandboxed=sandboxed,
            send_files=_bool(e.get("SEND_FILES"), True),
            send_roots=send_roots,
            send_max_mb=send_max_mb,
            upload_max_mb=upload_max_mb,
            tts=tts,
            extra_args=tuple(shlex.split(e.get("CLAUDE_EXTRA_ARGS", ""))),
        )
