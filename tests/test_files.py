import os

import pytest

from clautele.files import (
    SendError,
    is_video,
    video_system_prompt,
    extract_files,
    inbox_target,
    is_photo,
    resolve_sendable,
    safe_filename,
)

MB = 1024 * 1024


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    return w


def ok(ws, p, roots=None, max_bytes=50 * MB):
    return resolve_sendable(p, workdir=ws, roots=roots or (ws,), max_bytes=max_bytes)


def test_extract_json_plain_and_broken():
    text = (
        'Selesai.\n<<FILE>>{"path": "a.png", "caption": "Logo"}<<END>>\n'
        "<<FILE>>/x/b.pdf<<END>>\n<<FILE>><<END>>"
    )
    body, refs = extract_files(text)
    assert body == "Selesai."
    assert [(r.path, r.caption) for r in refs] == [("a.png", "Logo"), ("/x/b.pdf", "")]


def test_no_marker():
    assert extract_files("halo") == ("halo", [])


def test_relative_and_absolute_inside_workspace(ws):
    f = ws / "out" / "a.txt"
    f.parent.mkdir()
    f.write_text("isi")
    assert ok(ws, "out/a.txt") == f.resolve()
    assert ok(ws, str(f)) == f.resolve()


def test_missing_directory_and_empty(ws):
    (ws / "d").mkdir()
    (ws / "kosong.txt").write_text("")
    for p, msg in [("tidak-ada.txt", "tidak ditemukan"), ("d", "bukan file"), ("kosong.txt", "kosong"), ("", "kosong")]:
        with pytest.raises(SendError, match=msg):
            ok(ws, p)


def test_outside_roots_blocked(ws, tmp_path):
    secret = tmp_path / "luar.txt"
    secret.write_text("rahasia")
    with pytest.raises(SendError, match="SEND_ROOTS"):
        ok(ws, str(secret))
    with pytest.raises(SendError, match="SEND_ROOTS"):
        ok(ws, "../luar.txt")  # path traversal


def test_symlink_escape_blocked(ws, tmp_path):
    target = tmp_path / "luar.txt"
    target.write_text("rahasia")
    (ws / "tautan.txt").symlink_to(target)
    with pytest.raises(SendError, match="SEND_ROOTS"):
        ok(ws, "tautan.txt")


def test_symlink_to_secret_name_inside_workspace_blocked(ws):
    (ws / ".env").write_text("TOKEN=x")
    (ws / "polos.txt").symlink_to(ws / ".env")
    with pytest.raises(SendError, match="diblokir"):
        ok(ws, "polos.txt")


@pytest.mark.parametrize(
    "name", [".env", ".env.production", "server.pem", "x.KEY", "id_rsa", "id_ed25519.pub", ".credentials.json", "credentials.json", ".netrc", "state.json"]
)
def test_secret_names_blocked(ws, name):
    (ws / name).write_text("x")
    with pytest.raises(SendError, match="diblokir"):
        ok(ws, name)


def test_example_env_allowed(ws):
    (ws / ".env.example").write_text("A=")
    assert ok(ws, ".env.example").name == ".env.example"


@pytest.mark.parametrize("d", [".ssh", ".aws", ".claude", "claude-config", ".git"])
def test_secret_dirs_blocked(ws, d):
    (ws / d).mkdir()
    (ws / d / "config").write_text("x")
    with pytest.raises(SendError, match="folder"):
        ok(ws, f"{d}/config")


def test_size_limit(ws):
    (ws / "besar.bin").write_bytes(b"x" * (2 * MB))
    with pytest.raises(SendError, match="terlalu besar"):
        ok(ws, "besar.bin", max_bytes=1 * MB)


def test_extra_root_allowed(ws, tmp_path):
    other = tmp_path / "laporan"
    other.mkdir()
    (other / "r.pdf").write_text("pdf")
    assert ok(ws, str(other / "r.pdf"), roots=(ws, other)).name == "r.pdf"


def test_is_photo(ws):
    (ws / "a.png").write_bytes(b"x")
    (ws / "a.svg").write_bytes(b"x")
    assert is_photo(ws / "a.png") and not is_photo(ws / "a.svg")


def test_safe_filename():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("laporan akhir (1).pdf") == "laporan_akhir_1_.pdf" or safe_filename("laporan akhir (1).pdf").endswith(".pdf")
    assert safe_filename(".bashrc") == "bashrc"
    assert safe_filename(None, "foto") == "foto"
    assert safe_filename("x" * 300).__len__() == 100
    assert "/" not in safe_filename("a/b\\c")


def test_inbox_target_unique(tmp_path):
    a = inbox_target(tmp_path / "in", "x.jpg", fallback="foto", now=1_700_000_000)
    a.write_text("1")
    b = inbox_target(tmp_path / "in", "x.jpg", fallback="foto", now=1_700_000_000)
    assert a != b and b.parent == a.parent


def test_is_video(ws):
    for n, expected in [("a.mp4", True), ("a.MOV", True), ("a.m4v", True), ("a.mkv", False), ("a.png", False)]:
        assert is_video(ws / n) is expected, n


def test_video_prompt_content(ws):
    text = video_system_prompt(ws / "out", ws / "in", 50)
    for needle in ("libx264", "yuv420p", "faststart", "ffprobe", "45 MB", str(ws / "out"), str(ws / "in"), "Read"):
        assert needle in text, needle
