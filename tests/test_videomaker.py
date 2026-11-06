import dataclasses
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from helpers_tts import SECRET, Server, make_wav

from clautele import videomaker as vm
from clautele.tts import TtsConfig
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


# ---------- narasi (TTS) ----------


@pytest.fixture
def tts_srv():
    s = Server()
    yield s
    s.close()


def tts_cfg(srv):
    return TtsConfig.from_env({"TTS_BASE_URL": srv.url, "TTS_BASIC_AUTH": f"u:{SECRET}", "TTS_VOICE": "adult"})


def spec_file(tmp_path, scenes, **extra):
    (tmp_path / "s.json").write_text(json.dumps({"size": "320x568", "fps": 15, "scenes": scenes, **extra}))


def streams(path):
    info = probe(path)
    return {s["codec_type"]: s for s in info["streams"]}, float(info["format"]["duration"])


def test_narration_limits(tmp_path):
    with pytest.raises(SpecError, match="terlalu panjang"):
        spec_of(tmp_path, scenes=[{"title": "a", "narration": "x" * 501}])
    with pytest.raises(SpecError, match="total narasi"):
        spec_of(tmp_path, scenes=[{"title": "a", "narration": "x" * 400}] * 16)
    assert spec_of(tmp_path, scenes=[{"title": "a", "narration": "Halo"}]).scenes[0].narration == "Halo"


def test_scene_without_audio_keeps_an_flag(tmp_path):
    sp = spec_of(tmp_path)
    sc = sp.scenes[0]
    plain = vm.scene_command(sp, sc, layout(sp, sc), [], tmp_path / "o.mp4")
    assert "-an" in plain and "-map" in plain  # tanpa narasi: perilaku lama
    silent = vm.scene_command(sp, sc, layout(sp, sc), [], tmp_path / "o.mp4", with_audio=True)
    assert "anullsrc=r=44100:cl=stereo" in silent and "-an" not in silent


@needs_ffmpeg
def test_narration_extends_scene_and_adds_audio_to_every_segment(tmp_path, monkeypatch, tts_srv):
    monkeypatch.chdir(tmp_path)
    wav = make_wav(2.5)  # server tiruan membalas WAV 2,5 detik; ffprobe sungguhan mengukurnya
    monkeypatch.setattr("helpers_tts.make_wav", lambda *a, **k: wav)
    sp = vm.parse_spec(
        {"size": "320x568", "fps": 15, "scenes": [{"title": "A", "narration": "Halo dunia", "duration": 1}, {"title": "B", "duration": 1}]},
        base_dir=tmp_path,
    )
    vm.render(sp, tmp_path / "o.mp4", tts_cfg=tts_cfg(tts_srv), log=lambda m: None)
    st, dur = streams(tmp_path / "o.mp4")
    assert "audio" in st and st["audio"]["codec_name"] == "aac"  # scene tanpa narasi ikut punya trek audio
    # scene A diperpanjang: 0.4 + 2.5 + 0.6 = 3.5 detik; scene B tetap 1 detik
    assert abs(dur - 4.5) < 0.4
    req = [r for r in tts_srv.requests if r["path"] == "/v1/audio/speech"]
    assert len(req) == 1 and json.loads(req[0]["body"])["voice"] == "adult"  # hanya scene bernarasi yang disintesis


@needs_ffmpeg
def test_narration_without_tts_configured_fails_fast(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec_file(tmp_path, [{"title": "A", "narration": "Halo"}])
    for k in ("TTS_BASE_URL", "TTS_BASIC_AUTH"):
        monkeypatch.delenv(k, raising=False)
    assert vm.main(["s.json", "o.mp4"]) == 1
    assert not (tmp_path / "o.mp4").exists()


@needs_ffmpeg
def test_tts_failure_aborts_before_rendering(tmp_path, monkeypatch, tts_srv, capsys):
    monkeypatch.chdir(tmp_path)
    tts_srv.mode = "401"
    monkeypatch.setenv("TTS_BASE_URL", tts_srv.url)
    monkeypatch.setenv("TTS_BASIC_AUTH", f"u:{SECRET}")
    spec_file(tmp_path, [{"title": "A", "narration": "Halo", "duration": 1}, {"title": "B", "duration": 1}])
    assert vm.main(["s.json", "o.mp4"]) == 1
    err = capsys.readouterr().err
    assert "TTS gagal pada scene 1" in err and "kredensial ditolak" in err and SECRET not in err
    assert "scene 1/2" not in err  # gagal cepat: tidak ada render yang dimulai
    assert not (tmp_path / "o.mp4").exists()


@needs_ffmpeg
def test_music_shorter_than_video_is_looped_not_truncating(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "musik.mp3"], check=True)
    spec_file(tmp_path, [{"title": "a", "duration": 3}], audio="musik.mp3")
    assert vm.main(["s.json", "o.mp4"]) == 0
    st, dur = streams(tmp_path / "o.mp4")
    assert abs(dur - 3.0) < 0.3 and "audio" in st  # sebelumnya video terpotong jadi ~1 detik


@needs_ffmpeg
def test_narration_plus_music_mixed(tmp_path, monkeypatch, tts_srv):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("clautele.videomaker.audio_duration", lambda p: 1.0)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "musik.mp3"], check=True)
    sp = vm.parse_spec(
        {"size": "320x568", "fps": 15, "audio": "musik.mp3", "scenes": [{"title": "A", "narration": "Halo", "duration": 1}, {"title": "B", "duration": 2}]},
        base_dir=tmp_path,
    )
    vm.render(sp, tmp_path / "o.mp4", tts_cfg=tts_cfg(tts_srv), log=lambda m: None)
    st, dur = streams(tmp_path / "o.mp4")
    assert "audio" in st and abs(dur - (0.4 + 1.0 + 0.6 + 2)) < 0.4  # musik 1 detik diulang menutup seluruh video


@needs_ffmpeg
def test_unknown_voice_aborts_before_any_synthesis(tmp_path, monkeypatch, tts_srv, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TTS_BASE_URL", tts_srv.url)
    monkeypatch.setenv("TTS_BASIC_AUTH", f"u:{SECRET}")
    monkeypatch.setenv("TTS_VOICE", "suara-tidak-ada")
    spec_file(tmp_path, [{"title": "A", "narration": "Halo", "duration": 1}])
    assert vm.main(["s.json", "o.mp4"]) == 1
    assert "DIAM-DIAM" in capsys.readouterr().err
    assert not [r for r in tts_srv.requests if r["path"] == "/v1/audio/speech"]  # tak ada sintesis dengan suara bawaan
    assert not (tmp_path / "o.mp4").exists()


# ---------- ilustrasi (draw) ----------

from clautele import illustrate as il  # noqa: E402

HAS_PIL = importlib.util.find_spec("PIL") is not None
needs_pil = pytest.mark.skipif(not (HAS_FFMPEG and HAS_PIL), reason="ffmpeg/font/Pillow tidak ada")
SAMPLE_DRAW = [
    {"t": "floorplan", "x": 50, "y": 45, "size": 80, "labels": ["Tamu", "Dapur"]},
    {"t": "icon", "name": "database", "x": 20, "y": 80, "size": 18, "label": "Data", "at": 0.5, "anim": "pop", "loop": "pulse"},
    {"t": "arrow", "x1": 30, "y1": 80, "x2": 70, "y2": 80, "dots": True, "at": 1},
    {"t": "box", "x": 80, "y": 80, "w": 30, "h": 12, "text": "APP"},
    {"t": "bars", "x": 50, "y": 60, "w": 40, "h": 20, "values": [1, 3, 2]},
    {"t": "chaos", "x": 50, "y": 30, "count": 8, "color2": "green"},
    {"t": "text", "x": 50, "y": 95, "text": "halo", "anim": "type"},
    {"t": "poly", "points": [[10, 10], [50, 30], [90, 10]], "dots": True},
]


def test_draw_parsed_and_scene_may_have_only_drawing(tmp_path):
    sp = spec_of(tmp_path, scenes=[{"draw": SAMPLE_DRAW}])
    assert len(sp.scenes[0].draw) == len(SAMPLE_DRAW)
    assert sp.scenes[0].draw[1].p["anim"] == "pop" and sp.scenes[0].draw[3].p["fill"] is True  # box: isi default


@pytest.mark.parametrize(
    "draw, msg",
    [
        ("x", "daftar"),
        ([1], "objek"),
        ([{"t": "naga"}], "tidak dikenal"),
        ([{"t": "icon", "name": "unicorn"}], "name"),
        ([{"t": "icon", "name": "gear", "size": 999}], "size"),
        ([{"t": "icon", "name": "gear", "x": "tengah"}], "angka"),
        ([{"t": "icon", "name": "gear", "anim": "meledak"}], "anim"),
        ([{"t": "icon", "name": "gear", "loop": "gila"}], "loop"),
        ([{"t": "icon", "name": "gear", "color": "ungu muda"}], "color"),
        ([{"t": "text"}], "text wajib"),
        ([{"t": "text", "text": "x" * 100}], "terlalu panjang"),
        ([{"t": "poly", "points": [[1, 2]]}], "points"),
        ([{"t": "poly", "points": [[1, "a"], [2, 3]]}], "x,y"),
        ([{"t": "bars", "values": []}], "values"),
        ([{"t": "bars", "values": [-1]}], "values"),
        ([{"t": "floorplan", "labels": list("abcde")}], "maks 4"),
        ([{"t": "rect", "fill": "ya"}], "fill"),
        ([{"t": "rect"}] * 61, "maksimal"),
    ],
)
def test_invalid_draw_rejected(tmp_path, draw, msg):
    with pytest.raises(SpecError, match=msg):
        spec_of(tmp_path, scenes=[{"title": "a", "draw": draw}])


def test_every_icon_builds_and_stays_near_unit_box():
    for name in il.ICON_NAMES:
        shapes = il._icon_shapes(name)
        assert shapes, name
        for s in shapes:
            assert all(abs(x) <= 1.3 and abs(y) <= 1.3 for x, y in s.pts), name


def test_layout_with_drawing_keeps_text_in_top_strip(tmp_path):
    for size in ("story", "portrait", "square", "landscape"):
        sp = spec_of(tmp_path, size=size, footer="@a", scenes=[{"label": "01", "title": "Architecture Vision untuk semua", "body": "isi " * 40, "draw": SAMPLE_DRAW}])
        top = [ln for ln in layout(sp, sp.scenes[0]) if ln.text != "@a"]
        _, sy, _, _ = il.stage_rect(sp.width, sp.height)
        assert all(ln.y >= 0 for ln in top), size
        assert max(ln.y for ln in top) < sy, size  # baris teks mulai di atas panggung gambar


@needs_pil
def test_stage_frames_animate_and_have_right_size():
    els = il.parse_elements(SAMPLE_DRAW, 1, lambda v: vm.PALETTE.get(v, v))
    st = il.Stage(540, 960, vm.PALETTE["cyan"], els, vm.FONT)
    f0, f1, f2 = st.frame(0.2), st.frame(1.5), st.frame(5.0)
    assert len(f0) == st.sw * st.sh * 3
    assert f0 != f1 != f2  # ada gerak: gambar bertambah seiring waktu
    assert sum(f2) > sum(f0)


def test_scene_command_pipes_illustration_and_shifts_audio_index(tmp_path):
    sp = spec_of(tmp_path, scenes=[{"title": "a", "draw": [{"t": "icon", "name": "star"}]}])
    sc = sp.scenes[0]
    cmd = vm.scene_command(sp, sc, layout(sp, sc), [], tmp_path / "o.mp4", with_audio=True)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "rawvideo" in cmd and "[3:v]" in graph and "[4:a]" in graph and "[illus]" in graph
    plain = vm.scene_command(sp, dataclasses.replace(sc, draw=()), layout(sp, sc), [], tmp_path / "o.mp4", with_audio=True)
    assert "rawvideo" not in plain and "[3:a]" in plain[plain.index("-filter_complex") + 1]  # tanpa draw: perilaku lama


@needs_pil
def test_render_drawn_scene_with_narration(tmp_path, monkeypatch, tts_srv):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("clautele.videomaker.audio_duration", lambda p: 1.0)
    sp = vm.parse_spec(
        {
            "size": "320x568", "fps": 15,
            "scenes": [
                {"title": "Peta", "narration": "Halo", "duration": 1, "draw": SAMPLE_DRAW},
                {"title": "Teks saja", "duration": 1},
            ],
        },
        base_dir=tmp_path,
    )
    vm.render(sp, tmp_path / "o.mp4", tts_cfg=tts_cfg(tts_srv), log=lambda m: None)
    st, dur = streams(tmp_path / "o.mp4")
    assert st["video"]["codec_name"] == "h264" and "audio" in st
    assert abs(dur - (0.4 + 1.0 + 0.6 + 1)) < 0.4


@needs_pil
def test_render_drawn_video_without_audio(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "s.json").write_text(json.dumps({"size": "320x568", "fps": 15, "scenes": [{"title": "Denah", "duration": 2, "draw": SAMPLE_DRAW}]}))
    assert vm.main(["s.json", "o.mp4"]) == 0
    st, dur = streams(tmp_path / "o.mp4")
    assert "audio" not in st and abs(dur - 2.0) < 0.3


def test_draw_without_pillow_gives_clear_error(tmp_path, monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no PIL")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    sp = spec_of(tmp_path, scenes=[{"title": "a", "draw": [{"t": "icon", "name": "star"}]}])
    with pytest.raises(SpecError, match="Pillow"):
        vm._run_scene(["true"], sp, sp.scenes[0], tmp_path)
