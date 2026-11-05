import pytest

from clautele.config import Config, ConfigError

BASE = {"TELEGRAM_BOT_TOKEN": "123:abc", "ALLOWED_USER_IDS": "42, 99"}


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
