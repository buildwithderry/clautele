"""2FA TOTP (RFC 6238) tanpa dependensi, plus gerbang login untuk bot.

Setup:   python -m clautele.totp            (buat secret baru + URI otpauth)
Cek:     python -m clautele.totp --verify 123456   (pakai TOTP_SECRET dari .env)
"""

from __future__ import annotations

import base64
import binascii
import hmac
import os
import secrets
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

STEP = 30
DIGITS = 6
WINDOW = 1  # toleransi ±1 langkah (30 detik) untuk selisih jam
MIN_SECRET_CHARS = 16  # base32; 16 karakter = 80 bit


class TotpError(ValueError):
    pass


def generate_secret() -> str:
    """160 bit acak, base32 tanpa padding (format yang diterima aplikasi authenticator)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret_b32: str) -> bytes:
    s = secret_b32.replace(" ", "").replace("-", "").upper()
    if len(s) < MIN_SECRET_CHARS:
        raise TotpError(f"TOTP_SECRET terlalu pendek (minimal {MIN_SECRET_CHARS} karakter base32).")
    try:
        return base64.b32decode(s + "=" * (-len(s) % 8))
    except (binascii.Error, ValueError) as exc:
        raise TotpError("TOTP_SECRET bukan base32 yang valid (huruf A-Z dan angka 2-7).") from exc


def validate_secret(secret_b32: str) -> None:
    _key(secret_b32)


def code_at(secret_b32: str, counter: int, digits: int = DIGITS) -> str:
    mac = hmac.new(_key(secret_b32), struct.pack(">Q", counter), "sha1").digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def verify(secret_b32: str, code: str, now: float | None = None) -> int | None:
    """Kembalikan nomor langkah waktu yang cocok, atau None. Waktu konstan terhadap isi kode."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == DIGITS):
        return None
    current = int((time.time() if now is None else now) // STEP)
    matched: int | None = None
    for counter in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(code_at(secret_b32, counter), code):
            matched = counter  # tidak break: durasi tetap sama
    return matched


def otpauth_uri(secret_b32: str, account: str = "bot", issuer: str = "Clautele") -> str:
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(account)}"
        f"?secret={secret_b32}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"
    )


@dataclass
class _UserAuth:
    unlocked_until: float = 0.0
    last_step: int = -1  # cegah pemakaian ulang kode yang sama
    failures: int = 0
    locked_until: float = 0.0


@dataclass
class TotpGate:
    """Status login per user, hanya di memori: restart bot = terkunci lagi."""

    secret: str | None
    session_seconds: int = 3600
    max_failures: int = 5
    lockout_seconds: int = 900
    _users: dict[int, _UserAuth] = field(default_factory=dict)

    @property
    def required(self) -> bool:
        return bool(self.secret)

    def _u(self, uid: int) -> _UserAuth:
        return self._users.setdefault(uid, _UserAuth())

    def is_unlocked(self, uid: int, now: float | None = None) -> bool:
        if not self.required:
            return True
        now = time.time() if now is None else now
        return now < self._u(uid).unlocked_until

    def unlocked_until(self, uid: int) -> float:
        return self._u(uid).unlocked_until

    def lock(self, uid: int) -> None:
        self._u(uid).unlocked_until = 0.0

    def attempt(self, uid: int, code: str, now: float | None = None) -> tuple[bool, str]:
        if not self.required:
            return True, "2FA tidak aktif."
        now = time.time() if now is None else now
        u = self._u(uid)
        if now < u.locked_until:
            wait = int(u.locked_until - now) // 60 + 1
            return False, f"Terlalu banyak percobaan salah. Coba lagi sekitar {wait} menit."
        step = verify(self.secret or "", code, now)
        if step is None or step <= u.last_step:
            u.failures += 1
            if u.failures >= self.max_failures:
                u.failures = 0
                u.locked_until = now + self.lockout_seconds
                return False, f"Kode salah {self.max_failures}x. Dikunci {self.lockout_seconds // 60} menit."
            return False, f"Kode salah atau sudah dipakai. Sisa percobaan: {self.max_failures - u.failures}."
        u.failures = 0
        u.last_step = step
        u.unlocked_until = now + self.session_seconds
        return True, f"Terbuka selama {self.session_seconds // 60} menit."


def _read_env_secret() -> str:
    from .config import load_dotenv

    load_dotenv(Path(".env"))
    return os.environ.get("TOTP_SECRET", "").strip()


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--verify":
        secret = _read_env_secret()
        if not secret:
            print("TOTP_SECRET belum ada di .env", file=sys.stderr)
            return 2
        ok = verify(secret, argv[1]) is not None
        print("COCOK" if ok else "TIDAK COCOK (cek jam server dan secret di aplikasi)")
        return 0 if ok else 1

    secret = generate_secret()
    print(
        "Secret 2FA baru (JANGAN dibagikan; jalankan ini di terminal pribadi, bukan di chat):\n\n"
        f"  TOTP_SECRET={secret}\n\n"
        "1. Tambahkan baris di atas ke .env\n"
        "2. Di aplikasi authenticator pilih 'Masukkan kunci setup' (manual), akun bebas, tipe 'berbasis waktu':\n"
        f"   kunci: {secret}\n"
        f"   atau URI: {otpauth_uri(secret)}\n"
        "3. Uji pairing:  python -m clautele.totp --verify <kode 6 digit>\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
