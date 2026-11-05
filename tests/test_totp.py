import time

import pytest

from clautele import totp
from clautele.config import Config, ConfigError
from clautele.totp import TotpGate, code_at, generate_secret, verify

# Vektor uji RFC 6238 (SHA1): secret ASCII "12345678901234567890"
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def test_rfc6238_vectors():
    # 6 digit terakhir dari kode 8 digit di lampiran RFC
    assert code_at(RFC_SECRET, 59 // 30) == "287082"
    assert code_at(RFC_SECRET, 1111111109 // 30) == "081804"
    assert code_at(RFC_SECRET, 2000000000 // 30) == "279037"


def test_verify_window_and_format():
    now = 1_700_000_000
    good = code_at(RFC_SECRET, now // 30)
    assert verify(RFC_SECRET, good, now) == now // 30
    assert verify(RFC_SECRET, good, now + 30) is not None  # toleransi ±1 langkah
    assert verify(RFC_SECRET, good, now + 120) is None  # di luar jendela
    for bad in ("", "abc123", "12345", "1234567", "000000"):
        assert verify(RFC_SECRET, bad, now) is None or bad == good


def test_secret_validation_and_generation():
    s = generate_secret()
    assert len(s) >= 32 and s != generate_secret()
    totp.validate_secret(s)
    with pytest.raises(totp.TotpError):
        totp.validate_secret("pendek")
    with pytest.raises(totp.TotpError):
        totp.validate_secret("!" * 20)
    assert totp.otpauth_uri(s).startswith("otpauth://totp/Clautele:")


def test_gate_login_replay_and_expiry():
    gate = TotpGate(RFC_SECRET, session_seconds=600)
    now = 1_700_000_000
    code = code_at(RFC_SECRET, now // 30)

    assert not gate.is_unlocked(1, now)
    ok, _ = gate.attempt(1, code, now)
    assert ok and gate.is_unlocked(1, now + 599)
    assert not gate.is_unlocked(1, now + 601)  # sesi kedaluwarsa
    assert not gate.is_unlocked(2, now)  # per user

    gate.lock(1)
    ok, _ = gate.attempt(1, code, now + 1)  # kode yang sama tidak boleh dipakai ulang
    assert not ok and not gate.is_unlocked(1, now + 1)

    ok, _ = gate.attempt(1, code_at(RFC_SECRET, now // 30 + 1), now + 31)
    assert ok


def test_gate_lockout_after_failures():
    gate = TotpGate(RFC_SECRET, max_failures=3, lockout_seconds=900)
    now = 1_700_000_000
    for _ in range(3):
        ok, _ = gate.attempt(1, "000000", now)
        assert not ok
    # setelah terkunci, bahkan kode benar ditolak
    ok, msg = gate.attempt(1, code_at(RFC_SECRET, now // 30), now + 10)
    assert not ok and "menit" in msg
    ok, _ = gate.attempt(1, code_at(RFC_SECRET, (now + 901) // 30), now + 901)
    assert ok


def test_gate_disabled_without_secret():
    gate = TotpGate(None)
    assert not gate.required and gate.is_unlocked(1)


def test_config_host_mode_requires_totp():
    base = {"TELEGRAM_BOT_TOKEN": "1:x", "ALLOWED_USER_IDS": "1"}
    with pytest.raises(ConfigError, match="WAJIB memakai 2FA"):
        Config.from_env(base)
    cfg = Config.from_env({**base, "TOTP_SECRET": RFC_SECRET})
    assert cfg.totp_secret == RFC_SECRET and not cfg.sandboxed
    # Docker: opsional
    assert Config.from_env({**base, "CLAUTELE_SANDBOX": "docker"}).totp_secret is None


def test_config_rejects_bad_totp_values():
    base = {"TELEGRAM_BOT_TOKEN": "1:x", "ALLOWED_USER_IDS": "1", "CLAUTELE_SANDBOX": "docker"}
    with pytest.raises(ConfigError):
        Config.from_env({**base, "TOTP_SECRET": "pendek"})
    with pytest.raises(ConfigError):
        Config.from_env({**base, "TOTP_SECRET": RFC_SECRET, "TOTP_SESSION_MINUTES": "0"})
