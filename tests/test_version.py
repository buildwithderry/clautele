"""Cegah versi di kode dan CHANGELOG berbeda saat rilis."""

import re
from pathlib import Path

from clautele import __version__

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def test_semver_format():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_changelog_latest_release_matches_version():
    text = CHANGELOG.read_text(encoding="utf-8")
    released = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.MULTILINE)
    assert released, "CHANGELOG belum punya versi rilis"
    assert released[0] == __version__, f"CHANGELOG teratas {released[0]} != __version__ {__version__}"
