import json
import shutil
import subprocess
from pathlib import Path

import pytest

from clautele import videomaker as vm
from clautele.videomaker import SpecError, Scene, Spec, fit, layout, parse_spec, wrap

HAS_FFMPEG = shutil.which("ffmpeg") is not None and Path(vm.FONT).is_file()
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/font tidak ada")


def spec_of(base, **over):
    data = {"scenes": [{"title": "Halo"}], **over}
    return parse_spec(data, base_dir=base)


def test_defaults(tmp_path):
    s = spec_of(tmp_path)
    assert (s.width, s.height, s.fps) == (1080, 1920, 30)
    assert s.scenes[0].duration == 4 and s.scenes[0].color == vm.PALETTE["cyan"]
    assert s.audio is None and s.footer == ""


def test_colors_cycle_and_hex(tmp_path):
    s = spec_of(tmp_path, scenes=[{"title": "a"}, {"title": "b"}, {"title": "c", "color": "#ff00aa"}, {"title": "d", "color": "MAGENTA"}])
    assert [sc.color for sc in s.scenes] == [vm.PALETTE["cyan"], vm.PALETTE["magenta"], "FF00AA", vm.PALETTE["magenta"]]


@pytest.mark.parametrize(
    "over, msg",
    [
        ({"size": "huge"}, "size"),
        ({"size": "1081x1920"}, "genap"),
        ({"size": "100x100"}, "genap"),
        ({"fps": 5}, "fps"),
        ({"fps": "abc"}, "fps"),
        ({"scenes": []}, "scenes"),
        ({"scenes": "x"}, "scenes"),
        ({"scenes": [{"title": "a", "duration": 0}]}, "duration"),
        ({"scenes": [{"title": "a", "duration": 99}]}, "duration"),
        ({"scenes": [{}]}, "isi title"),
        ({"scenes": [{"title": "a", "color": "ungu muda"}]}, "color"),
        ({"scenes": [{"title": "x" * 200}]}, "terlalu panjang"),
        ({"scenes": [{"title": "a", "duration": 30}] * 7}, "melebihi batas"),
        ({"scenes": [{"title": "a"}] * 41}, "maksimal"),
        ({"audio": "tidak-ada.mp3"}, "tidak ditemukan"),
        ({"audio": "../luar.mp3"}, "folder kerja"),
    ],
)
def test_invalid_specs_rejected(tmp_path, over, msg):
    with pytest.raises(SpecError, match=msg):
        spec_of(tmp_path, **over)


def test_non_object_spec(tmp_path):
    with pytest.raises(SpecError):
        parse_spec([1], base_dir=tmp_path)


def test_custom_size_and_audio_inside(tmp_path):
    (tmp_path / "m.mp3").write_bytes(b"x")
    s = spec_of(tmp_path, size="540x960", audio="m.mp3")
    assert (s.width, s.height) == (540, 960) and s.audio == (tmp_path / "m.mp3").resolve()


def test_wrap_and_fit():
    lines = wrap("kata " * 30, 80, 800)
    assert len(lines) > 1 and all(vm.est_width(l, 80) <= 800 for l in lines)
    assert "".join(wrap("x" * 100, 80, 800)) == "x" * 100  # kata panjang dipotong paksa, tidak hilang
    size, ls = fit("kata " * 40, 60, 30, 800, 4)
    assert size < 60 and len(ls) <= 4


def test_uppercase_is_wider_than_lowercase():
    assert vm.est_width("IMPLEMENTATION", 100) > vm.est_width("implementation", 100) * 1.15


def test_long_uppercase_word_shrinks_instead_of_splitting_mid_word():
    # regresi: "IMPLEMENTATION GOVERNANCE" sempat terpotong jadi "IMPLEMENTATIO" / "N GOVERNANCE"
    size, lines = fit("IMPLEMENTATION GOVERNANCE", 95, 54, 907, 5)
    assert lines == ["IMPLEMENTATION", "GOVERNANCE"] and size < 95


def test_layout_stays_inside_canvas(tmp_path):
    long_body = "Enterprise Architecture adalah disiplin yang menyelaraskan strategi bisnis dengan teknologi informasi. " * 3
    for size in ("story", "square", "portrait", "landscape"):
        sp = spec_of(tmp_path, size=size, footer="@akun", scenes=[{"label": "FASE A", "title": "Architecture Vision untuk semua orang", "body": long_body}])
        for ln in layout(sp, sp.scenes[0]):
            assert 0 <= ln.y and ln.y + ln.size <= sp.height, (size, ln)
            assert len(ln.text) * ln.size * 0.55 <= sp.width, (size, ln)  # perkiraan: tidak melebar keluar


def test_scene_command_uses_rgb_blend(tmp_path):
    sp = spec_of(tmp_path)
    sc = sp.scenes[0]
    cmd = vm.scene_command(sp, sc, layout(sp, sc), [tmp_path / "a.txt"], tmp_path / "o.mp4")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph.count("format=gbrp") >= 3 and "blend=all_mode=screen" in graph  # blend di RGB, bukan YUV
    assert "-an" in cmd and "yuv420p" in cmd


def test_cli_help_example_and_usage(capsys):
    assert vm.main(["--help"]) == 0 and "Spec JSON" in capsys.readouterr().out
    assert vm.main(["--example"]) == 0
    json.loads(capsys.readouterr().out)  # contoh harus JSON valid
    assert vm.main(["a"]) == 2


def test_cli_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert vm.main(["tidak-ada.json", "o.mp4"]) == 1 and "tidak ditemukan" in capsys.readouterr().err
    (tmp_path / "bad.json").write_text("{rusak")
    assert vm.main(["bad.json", "o.mp4"]) == 1 and "JSON tidak valid" in capsys.readouterr().err
    (tmp_path / "ok.json").write_text(json.dumps({"scenes": [{"title": "a"}]}))
    assert vm.main(["ok.json", "../keluar.mp4"]) == 1 and "folder kerja" in capsys.readouterr().err
    assert vm.main(["ok.json", "o.avi"]) == 1 and ".mp4" in capsys.readouterr().err


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,codec_type,width,height", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


@needs_ffmpeg
def test_render_real_video_with_hostile_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    nasty = "Rp 1,5 juta: \"hebat\" 100% (50/50) \\o/ 'ok' ; [x] =y #z"
    (tmp_path / "s.json").write_text(
        json.dumps(
            {
                "size": "320x568",
                "fps": 15,
                "footer": "@akun:test",
                "scenes": [
                    {"label": "01", "title": nasty, "body": nasty, "duration": 1},
                    {"title": "Scene dua", "color": "#39ff14", "duration": 1},
                ],
            }
        )
    )
    assert vm.main(["s.json", "hasil/out.mp4"]) == 0
    info = probe(tmp_path / "hasil" / "out.mp4")
    video = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert (video["codec_name"], video["width"], video["height"]) == ("h264", 320, 568)
    assert abs(float(info["format"]["duration"]) - 2.0) < 0.3
    assert not [s for s in info["streams"] if s["codec_type"] == "audio"]


@needs_ffmpeg
def test_render_with_audio(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=5", "musik.mp3"], check=True)
    (tmp_path / "s.json").write_text(json.dumps({"size": "320x568", "fps": 15, "audio": "musik.mp3", "scenes": [{"title": "a", "duration": 1}]}))
    assert vm.main(["s.json", "out.mp4"]) == 0
    info = probe(tmp_path / "out.mp4")
    assert "aac" in [s["codec_name"] for s in info["streams"]]
    assert float(info["format"]["duration"]) < 1.6  # -shortest: audio 5 detik dipotong mengikuti video


def test_overlong_text_is_truncated_with_ellipsis_not_silently():
    size, lines = fit("kata " * 60, 40, 40, 400, 3)
    assert len(lines) == 3 and lines[-1].endswith("…") and size == 40


def test_landscape_long_text_fits_without_truncation(tmp_path):
    sp = spec_of(tmp_path, size="landscape", scenes=[{"title": "T", "body": "kata " * 79}])
    lines = layout(sp, sp.scenes[0])
    assert not lines[-1].text.endswith("…") and all(ln.y + ln.size <= sp.height for ln in lines)
