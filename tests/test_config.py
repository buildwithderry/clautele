import pytest

from clautele.config import Config, ConfigError

BASE = {"TELEGRAM_BOT_TOKEN": "123:abc", "ALLOWED_USER_IDS": "42, 99", "CLAUTELE_SANDBOX": "docker"}


def test_minimal_ok():
    cfg = Config.from_env(BASE)
    assert cfg.allowed_user_ids == frozenset({42, 99})
    assert cfg.permission_mode == "acceptEdits"
    assert cfg.stream_progress is True


def test_token_required():
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        Config.from_env({"ALLOWED_USER_IDS": "1"})


def test_allowlist_required():
    with pytest.raises(ConfigError, match="ALLOWED_USER_IDS"):
        Config.from_env({"TELEGRAM_BOT_TOKEN": "x"})


def test_allowlist_must_be_numeric():
    with pytest.raises(ConfigError, match="bukan angka"):
        Config.from_env({**BASE, "ALLOWED_USER_IDS": "abc"})


def test_bypass_needs_explicit_confirmation():
    with pytest.raises(ConfigError, match="ALLOW_BYPASS_PERMISSIONS"):
        Config.from_env({**BASE, "CLAUDE_PERMISSION_MODE": "bypassPermissions"})
    cfg = Config.from_env(
        {**BASE, "CLAUDE_PERMISSION_MODE": "bypassPermissions", "ALLOW_BYPASS_PERMISSIONS": "true"}
    )
    assert cfg.permission_mode == "bypassPermissions"


def test_invalid_mode():
    with pytest.raises(ConfigError, match="CLAUDE_PERMISSION_MODE"):
        Config.from_env({**BASE, "CLAUDE_PERMISSION_MODE": "yolo"})


def test_allowed_tools_shell_split():
    cfg = Config.from_env({**BASE, "CLAUDE_ALLOWED_TOOLS": 'Read "Bash(git status*)" Grep'})
    assert cfg.allowed_tools == ("Read", "Bash(git status*)", "Grep")


def test_budget_and_timeout():
    cfg = Config.from_env({**BASE, "CLAUDE_MAX_BUDGET_USD": "1.5", "CLAUDE_TIMEOUT_SECONDS": "60"})
    assert cfg.max_budget_usd == 1.5 and cfg.timeout_seconds == 60
    with pytest.raises(ConfigError):
        Config.from_env({**BASE, "CLAUDE_MAX_BUDGET_USD": "banyak"})


def test_load_dotenv(tmp_path):
    from clautele.config import load_dotenv

    f = tmp_path / ".env"
    f.write_text(
        "# komentar\n\nA=1\nB=Read Grep Glob\nC=\"dua kata\"\nexport D=4\nTAKADA\nA2=x=y\nEXISTING=baru\n"
    )
    env = {"EXISTING": "lama"}
    assert load_dotenv(f, env) == 5
    assert env["A"] == "1"
    assert env["B"] == "Read Grep Glob"  # nilai berspasi utuh
    assert env["C"] == "dua kata"  # kutip pembungkus dibuang
    assert env["D"] == "4"
    assert env["A2"] == "x=y"
    assert env["EXISTING"] == "lama"  # tidak menimpa
    assert load_dotenv(tmp_path / "tidak-ada", env) == 0


def test_send_roots_default_is_outbox_only(tmp_path):
    cfg = Config.from_env({**BASE, "CLAUDE_WORKDIR": str(tmp_path)})
    assert cfg.send_roots == (tmp_path.resolve() / ".clautele" / "outbox",)
    wide = Config.from_env({**BASE, "CLAUDE_WORKDIR": str(tmp_path), "SEND_ROOTS": f"{tmp_path}/a, {tmp_path}/b"})
    assert [r.name for r in wide.send_roots] == ["a", "b"]


def test_send_limits_validated():
    for k, v in [("SEND_MAX_MB", "51"), ("UPLOAD_MAX_MB", "21"), ("SEND_MAX_MB", "x")]:
        with pytest.raises(ConfigError):
            Config.from_env({**BASE, k: v})


def test_load_dotenv_duplicate_key_last_wins(tmp_path):
    from clautele.config import load_dotenv

    f = tmp_path / ".env"
    f.write_text("CLAUDE_ALLOWED_TOOLS=Read Grep Glob\nX=1\nCLAUDE_ALLOWED_TOOLS=Bash(ffmpeg *)\n")
    env: dict = {}
    assert load_dotenv(f, env) == 2  # dua kunci unik, bukan tiga baris
    assert env["CLAUDE_ALLOWED_TOOLS"] == "Bash(ffmpeg *)"  # sama dengan docker compose


def test_tts_config_is_optional_and_validated():
    assert Config.from_env(BASE).tts is None
    cfg = Config.from_env({**BASE, "TTS_BASE_URL": "https://x.example.com", "TTS_BASIC_AUTH": "u:p", "TTS_VOICE": "adult"})
    assert cfg.tts.voice == "adult" and "u:p" not in repr(cfg)
    with pytest.raises(ConfigError, match="TTS"):
        Config.from_env({**BASE, "TTS_BASE_URL": "http://example.com"})  # http ke host non-loopback ditolak
