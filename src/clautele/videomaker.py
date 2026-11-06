"""clautele-video: render video slide bergaya neon (MP4) dari spec JSON, memakai ffmpeg.

    clautele-video spec.json hasil.mp4
    clautele-video --example        # cetak contoh spec
    clautele-video --help           # skema lengkap

Dibuat agar Claude tidak perlu merangkai filter ffmpeg yang rumit: cukup menulis JSON, lalu satu perintah.
Setiap scene dirender dengan satu panggilan ffmpeg (latar gelap + grid + teks neon berpendar + bingkai),
lalu semua scene digabung. Scene dengan "draw" (ilustrasi) menggambar frame dengan Pillow dan mengalirkannya ke ffmpeg.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import illustrate
from .tts import TtsConfig, TtsError, audio_duration, resolve_voice, synthesize

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SIZES = {
    "story": (1080, 1920),
    "reels": (1080, 1920),
    "portrait": (1080, 1350),
    "square": (1080, 1080),
    "landscape": (1920, 1080),
}
PALETTE = {
    "cyan": "00F0FF",
    "magenta": "FF2BD6",
    "green": "39FF14",
    "yellow": "FFF01F",
    "orange": "FF8A00",
    "red": "FF3355",
    "blue": "3D7BFF",
    "purple": "B44DFF",
    "white": "FFFFFF",
}
CYCLE = ["cyan", "magenta", "green", "yellow", "purple", "orange"]
MAX_SCENES = 40
MAX_TOTAL_SECONDS = 180
MAX_NARRATION_CHARS = 500  # per scene
MAX_NARRATION_TOTAL = 6000
VOICE_LEAD = 0.4  # jeda sebelum suara mulai (detik)
VOICE_TAIL = 0.6  # jeda setelah suara selesai (detik)
MUSIC_VOLUME = 0.22  # musik latar saat ada narasi
BG = "07000F"
HEX_RE = re.compile(r"#?([0-9A-Fa-f]{6})")

SCHEMA_HELP = """\
Spec JSON:
{
  "size": "story",            // story|reels (1080x1920), portrait (1080x1350), square (1080x1080), landscape (1920x1080), atau WxH genap
  "fps": 30,                  // 15-60
  "footer": "@akunkamu",      // opsional, teks kecil di bawah setiap scene
  "audio": "musik.mp3",       // opsional, file audio di bawah folder kerja
  "scenes": [                 // 1-40 scene, total maks 180 detik
    {
      "label": "01",          // opsional, teks kecil di atas judul (nomor/kategori)
      "title": "APA ITU EA?", // judul besar, opsional
      "body": "Penjelasan.",  // isi, opsional (diperkecil otomatis, dibungkus per baris)
      "narration": "Teks yang dibacakan.", // opsional; butuh TTS (TTS_BASE_URL). Durasi scene menyesuaikan panjang suara
      "color": "cyan",        // cyan|magenta|green|yellow|orange|red|blue|purple|white|#RRGGBB (default: bergilir)
      "duration": 4,          // detik, 1-30 (default 4)
      "draw": [ ... ]         // opsional: ilustrasi animasi sesuai konteks (lihat di bawah)
    }
  ]
}
Tips: judul <= 6 kata, isi <= 2 kalimat, 3-5 detik per scene. Hasil: MP4 H.264 siap diunggah ke Instagram/Telegram.
Output harus berekstensi .mp4 dan berada di dalam folder kerja saat ini.

""" + illustrate.SCHEMA_DRAW_HELP

EXAMPLE = {
    "size": "story",
    "fps": 30,
    "footer": "@akunkamu",
    "scenes": [
        {"title": "ENTERPRISE ARCHITECTURE", "body": "Peta besar bisnis dan teknologi", "color": "cyan", "duration": 4},
        {
            "label": "01", "title": "APA ITU EA?", "body": "Peta besar bisnis dan IT.", "color": "magenta", "duration": 6,
            "draw": [
                {"t": "floorplan", "x": 50, "y": 45, "size": 85, "labels": ["Bisnis", "Data", "Aplikasi", "IT"]},
                {"t": "icon", "name": "bulb", "x": 88, "y": 8, "size": 14, "at": 3, "anim": "pop", "loop": "pulse", "color": "yellow"},
            ],
        },
        {
            "title": "DATA MENGALIR", "color": "green", "duration": 5,
            "draw": [
                {"t": "icon", "name": "person", "x": 15, "y": 40, "size": 20, "label": "User", "anim": "pop"},
                {"t": "arrow", "x1": 27, "y1": 40, "x2": 43, "y2": 40, "at": 0.8, "dots": True},
                {"t": "icon", "name": "app", "x": 55, "y": 40, "size": 20, "label": "Aplikasi", "at": 1.2, "anim": "pop"},
                {"t": "arrow", "x1": 67, "y1": 40, "x2": 80, "y2": 40, "at": 2, "dots": True},
                {"t": "icon", "name": "database", "x": 90, "y": 40, "size": 18, "label": "Data", "at": 2.4, "anim": "pop"},
            ],
        },
        {"title": "MAU TAHU CARA BUATNYA?", "body": "Tulis MAU di komentar!", "color": "green", "duration": 5},
    ],
}


class SpecError(ValueError):
    """Spec tidak valid; pesan aman ditampilkan ke user/Claude."""


@dataclass(frozen=True)
class Scene:
    label: str
    title: str
    body: str
    color: str  # RRGGBB
    duration: float
    narration: str = ""
    draw: tuple[illustrate.Element, ...] = ()


@dataclass(frozen=True)
class Spec:
    width: int
    height: int
    fps: int
    footer: str
    audio: Path | None
    scenes: tuple[Scene, ...] = field(default_factory=tuple)

    @property
    def total_seconds(self) -> float:
        return sum(s.duration for s in self.scenes)


def _color(value: Any, index: int) -> str:
    if value is None or value == "":
        value = CYCLE[index % len(CYCLE)]
    if not isinstance(value, str):
        raise SpecError(f"scene {index + 1}: color harus teks")
    if value.lower() in PALETTE:
        return PALETTE[value.lower()]
    m = HEX_RE.fullmatch(value.strip())
    if m:
        return m.group(1).upper()
    raise SpecError(f"scene {index + 1}: color '{value}' tidak dikenal (pakai {', '.join(PALETTE)} atau #RRGGBB)")


def _text(scene: dict[str, Any], key: str, limit: int, index: int) -> str:
    val = scene.get(key, "")
    if val is None:
        val = ""
    if not isinstance(val, (str, int, float)):
        raise SpecError(f"scene {index + 1}: {key} harus teks")
    val = " ".join(str(val).split())
    if len(val) > limit:
        raise SpecError(f"scene {index + 1}: {key} terlalu panjang ({len(val)} > {limit} karakter)")
    return val


def parse_spec(data: Any, *, base_dir: Path) -> Spec:
    if not isinstance(data, dict):
        raise SpecError("spec harus berupa objek JSON")
    size = str(data.get("size", "story")).lower()
    custom = re.fullmatch(r"(\d{3,4})x(\d{3,4})", size)
    if size in SIZES:
        width, height = SIZES[size]
    elif custom:
        width, height = int(custom.group(1)), int(custom.group(2))
        if not (240 <= width <= 2160 and 240 <= height <= 2160) or width % 2 or height % 2:
            raise SpecError("size WxH harus genap dan 240-2160 piksel per sisi")
    else:
        raise SpecError(f"size '{size}' tidak dikenal (pakai {', '.join(SIZES)} atau WxH, mis. 1080x1350)")

    try:
        fps = int(data.get("fps", 30))
    except (TypeError, ValueError):
        raise SpecError("fps harus bilangan bulat") from None
    if not 15 <= fps <= 60:
        raise SpecError("fps harus 15-60")

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise SpecError("scenes harus berupa daftar berisi minimal 1 scene")
    if len(raw_scenes) > MAX_SCENES:
        raise SpecError(f"maksimal {MAX_SCENES} scene")

    scenes: list[Scene] = []
    for i, sc in enumerate(raw_scenes):
        if not isinstance(sc, dict):
            raise SpecError(f"scene {i + 1} harus berupa objek")
        try:
            duration = float(sc.get("duration", 4))
        except (TypeError, ValueError):
            raise SpecError(f"scene {i + 1}: duration harus angka") from None
        if not 1 <= duration <= 30:
            raise SpecError(f"scene {i + 1}: duration harus 1-30 detik")
        title = _text(sc, "title", 120, i)
        body = _text(sc, "body", 400, i)
        label = _text(sc, "label", 40, i)
        narration = _text(sc, "narration", MAX_NARRATION_CHARS, i)
        try:
            draw = illustrate.parse_elements(sc.get("draw"), i + 1, lambda v, i=i: _color(v, i))
        except illustrate.DrawError as exc:
            raise SpecError(str(exc)) from None
        if not (title or body or label or draw):
            raise SpecError(f"scene {i + 1}: isi title, body, label, atau draw")
        scenes.append(Scene(label, title, body, _color(sc.get("color"), i), duration, narration, draw))

    if sum(len(s.narration) for s in scenes) > MAX_NARRATION_TOTAL:
        raise SpecError(f"total narasi melebihi {MAX_NARRATION_TOTAL} karakter")
    total = sum(s.duration for s in scenes)
    if total > MAX_TOTAL_SECONDS:
        raise SpecError(f"total durasi {total:.0f} detik melebihi batas {MAX_TOTAL_SECONDS} detik")

    footer = _text(data, "footer", 60, 0) if data.get("footer") else ""
    audio = None
    if data.get("audio"):
        audio = _inside(base_dir, Path(str(data["audio"])), must_exist=True, what="audio")
    return Spec(width, height, fps, footer, audio, tuple(scenes))


def _inside(base: Path, p: Path, *, must_exist: bool, what: str) -> Path:
    real = (p if p.is_absolute() else base / p).resolve()
    if not real.is_relative_to(base.resolve()):
        raise SpecError(f"{what} harus berada di dalam folder kerja ({base})")
    if must_exist and not real.is_file():
        raise SpecError(f"{what} tidak ditemukan: {p}")
    return real


# ---------- tata letak teks ----------

LINE_H = 1.28


def est_width(text: str, size: int) -> float:
    """Perkiraan lebar teks DejaVu Sans Bold (em per huruf): kapital jauh lebih lebar daripada huruf kecil."""
    em = 0.0
    for ch in text:
        if ch == " ":
            em += 0.36
        elif ch.isupper():
            em += 0.80
        elif ch.isdigit():
            em += 0.72
        elif ch in "il.,;:!|'":
            em += 0.38
        elif ch in "mwMW@":
            em += 0.98
        else:
            em += 0.66
    return em * size


def wrap(text: str, fontsize: int, max_width: int) -> list[str]:
    """Bungkus per kata menurut lebar perkiraan; kata yang lebih lebar dari satu baris dipotong paksa."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        while est_width(word, fontsize) > max_width and len(word) > 1:
            n = max(1, min(len(word) - 1, int(len(word) * max_width / est_width(word, fontsize))))
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:n])
            word = word[n:]
        trial = f"{cur} {word}".strip()
        if est_width(trial, fontsize) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit(text: str, start: int, minimum: int, max_width: int, max_lines: int) -> tuple[int, list[str]]:
    """Kecilkan huruf sampai tiap kata muat satu baris dan jumlah baris <= max_lines.
    Bila di ukuran minimum masih kelebihan baris, potong dengan '…' (tidak hilang diam-diam)."""
    size = start
    words = text.split()
    while True:
        too_wide = max((est_width(w, size) for w in words), default=0) > max_width
        lines = wrap(text, size, max_width)
        if (not too_wide and len(lines) <= max_lines) or size <= minimum:
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                lines[-1] = lines[-1].rstrip(" .,;:")[: max(1, len(lines[-1]) - 1)] + "…"
            return size, lines
        size -= 4


@dataclass(frozen=True)
class TextLine:
    text: str
    size: int
    y: int  # posisi atas baris
    delay: float


def _blocks(spec: Spec, scene: Scene, t_start: int, b_start: int, base: int) -> tuple[int, list[str], int, list[str]]:
    max_w = int(spec.width * 0.84)
    drawing = bool(scene.draw)  # dengan gambar, teks hanya di strip atas: lebih sedikit baris
    t_size, t_lines = fit(scene.title, t_start, int(base * (0.040 if drawing else 0.050)), max_w, 2 if drawing else 5) if scene.title else (0, [])
    b_size, b_lines = fit(scene.body, b_start, int(base * 0.034), max_w, 3 if drawing else 9) if scene.body else (0, [])
    return t_size, t_lines, b_size, b_lines


def layout(spec: Spec, scene: Scene) -> list[TextLine]:
    w, h = spec.width, spec.height
    base = min(w, h)  # ukuran huruf mengikuti sisi terpendek: landscape tidak meluap ke bawah
    label_size = int(base * 0.045)
    gap = int(base * (0.02 if scene.draw else 0.05))
    avail = int(h * 0.78)  # sisakan ruang untuk bingkai dan footer
    top = int(h * 0.06)
    if scene.draw:  # judul dipadatkan ke strip atas; sisanya untuk panggung gambar
        avail = int(h * illustrate.title_reserve(w, h)) - top
    label_h = int(label_size * LINE_H) + int(base * (0.015 if scene.draw else 0.04)) if scene.label else 0

    t_start, b_start = int(base * 0.088), int(base * 0.050)
    while True:
        t_size, t_lines, b_size, b_lines = _blocks(spec, scene, t_start, b_start, base)
        title_h = int(len(t_lines) * t_size * LINE_H) + (gap if scene.body and scene.title else 0)
        body_h = int(len(b_lines) * b_size * LINE_H)
        total = label_h + title_h + body_h
        if total <= avail or (b_start <= int(base * 0.034) and t_start <= int(base * (0.040 if scene.draw else 0.050))):
            break
        if b_start > int(base * 0.034):
            b_start -= 4
        else:
            t_start -= 4
    if scene.draw and total > avail and b_lines:  # strip judul terlalu sempit: potong isi, jangan tabrak gambar
        room = avail - label_h - title_h
        keep = max(1, room // max(1, int(b_size * LINE_H)))
        if keep < len(b_lines):
            b_lines = b_lines[:keep]
            b_lines[-1] = b_lines[-1].rstrip(" .,;:") + "…"

    out: list[TextLine] = []
    y = max(int(h * 0.1), (h - total) // 2 - (int(h * 0.02) if h >= w else 0))
    if scene.draw:
        y = top + int(base * 0.03)
    if scene.label:
        out.append(TextLine(scene.label, label_size, y, 0.0))
        y += label_h
    for line in t_lines:
        out.append(TextLine(line, t_size, y, 0.15 if scene.label else 0.0))
        y += int(t_size * LINE_H)
    if scene.body:
        if scene.title:
            y += gap
        for line in b_lines:
            out.append(TextLine(line, b_size, y, 0.55))
            y += int(b_size * LINE_H)
    if spec.footer:
        f_size = int(base * 0.034)
        out.append(TextLine(spec.footer, f_size, h - int(h * 0.075) - f_size, 0.3))
    return out


# ---------- ffmpeg ----------


def _mix_white(rrggbb: str, amount: float) -> str:
    r, g, b = (int(rrggbb[i : i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: int(c + (255 - c) * amount)
    return f"{mix(r):02X}{mix(g):02X}{mix(b):02X}"


def _text_chain(spec: Spec, scene: Scene, lines: list[TextLine], color: str, files: list[Path], border: bool) -> str:
    """Rantai filter: bingkai + semua baris teks pada lapisan hitam."""
    d = scene.duration
    parts: list[str] = []
    if border:
        m = int(spec.width * 0.045)
        parts.append(
            f"drawbox=x={m}:y={m}:w={spec.width - 2 * m}:h={spec.height - 2 * m}:color=0x{color}@0.95:t=6"
        )
    for ln, path in zip(lines, files):
        start = ln.delay
        alpha = f"clip(min((t-{start:.2f})/0.45,({d:.3f}-t)/0.45),0,1)"
        slide = f"{int(spec.height * 0.03)}*pow(1-clip((t-{start:.2f})/0.7,0,1),3)"
        parts.append(
            "drawtext="
            f"fontfile={FONT}:textfile={path}:fontsize={ln.size}:fontcolor=0x{color}:"
            f"x='(w-text_w)/2':y='{ln.y}+{slide}':alpha='{alpha}'"
        )
    return ",".join(parts) if parts else "null"


def scene_command(
    spec: Spec, scene: Scene, lines: list[TextLine], files: list[Path], out: Path,
    *, with_audio: bool = False, voice: Path | None = None,
) -> list[str]:
    w, h, fps, d = spec.width, spec.height, spec.fps, scene.duration
    grid = max(40, w // 18)
    core = _mix_white(scene.color, 0.65)
    half_w, half_h = w // 2, h // 2
    sig_big, sig_small = max(6, w // 90), max(2, w // 270)

    bg = (
        f"[0:v]drawgrid=w={grid}:h={grid}:t=2:color=0x{scene.color}@0.14,"
        f"drawgrid=w={grid * 4}:h={grid * 4}:t=3:color=0x{scene.color}@0.18,vignette=PI/3.2,format=gbrp[bg]"
    )
    glow_src = _text_chain(spec, scene, lines, scene.color, files, border=True)
    core_src = _text_chain(spec, scene, lines, core, files, border=True)
    # Blend "screen" hanya benar di ruang RGB; di YUV hitam (chroma 128) tergeser jadi warna. Karena itu gbrp.
    audio_graph: list[str] = []
    a_in = 4 if scene.draw else 3  # input video ilustrasi (pipa) menempati indeks 3
    if with_audio:
        if voice is not None:  # suara ditunda sedikit, lalu diisi hening sampai scene berakhir
            audio_graph = [
                f"[{a_in}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"adelay={int(VOICE_LEAD * 1000)}|{int(VOICE_LEAD * 1000)},apad[a]"
            ]
        else:  # scene tanpa narasi tetap perlu trek audio agar semua segmen seragam saat digabung
            audio_graph = [f"[{a_in}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a]"]
    illus_graph: list[str] = []
    final = "[bg][neon]blend=all_mode=screen,format=yuv420p[v]"
    if scene.draw:  # ilustrasi: frame dari pipa (RGB hitam + garis neon), diberi fade, diletakkan di panggung, lalu berpendar
        sx, sy, _, _ = illustrate.stage_rect(w, h)
        out_at = max(0.0, d - 0.4)
        illus_graph = [
            f"[3:v]fade=t=in:st=0:d=0.25,fade=t=out:st={out_at:.3f}:d=0.4,pad={w}:{h}:{sx}:{sy}:black,format=gbrp,split=3[i1][i2][i3]",
            f"[i1]scale={half_w}:{half_h},gblur=sigma={sig_big},scale={w}:{h}[ib]",
            f"[i2]scale={half_w}:{half_h},gblur=sigma={sig_small},scale={w}:{h}[is]",
            "[ib][is]blend=all_mode=screen[ig]",
            "[ig][i3]blend=all_mode=screen[illus]",
        ]
        final = "[bg][neon]blend=all_mode=screen[b1];[b1][illus]blend=all_mode=screen,format=yuv420p[v]"
    graph = ";".join(
        [
            *audio_graph,
            bg,
            f"[1:v]{glow_src},format=gbrp,split=2[g1][g2]",
            f"[g1]scale={half_w}:{half_h},gblur=sigma={sig_big},scale={w}:{h}[gb]",
            f"[g2]scale={half_w}:{half_h},gblur=sigma={sig_small},scale={w}:{h}[gs]",
            f"[2:v]{core_src},format=gbrp[core]",
            "[gb][gs]blend=all_mode=screen[g]",
            "[g][core]blend=all_mode=screen[neon]",
            *illus_graph,
            final,
        ]
    )
    src = lambda color: f"color=c=0x{color}:s={w}x{h}:r={fps}:d={d:.3f}"
    inputs = [
        "-f", "lavfi", "-i", src(BG),
        "-f", "lavfi", "-i", src("000000"),
        "-f", "lavfi", "-i", src("000000"),
    ]  # fmt: skip
    if scene.draw:
        _, _, sw, sh = illustrate.stage_rect(w, h)
        inputs += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{sw}x{sh}", "-framerate", str(fps), "-i", "-"]
    if with_audio:
        inputs += ["-i", str(voice)] if voice is not None else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    audio_out = (
        ["-map", "[a]", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", "-t", f"{d:.3f}"]
        if with_audio
        else ["-an"]
    )
    return [
        "ffmpeg", "-y", "-loglevel", "error", *inputs,
        "-filter_complex", graph, "-map", "[v]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps),
        *audio_out, str(out),
    ]  # fmt: skip


def concat_command(list_file: Path, spec: Spec, out: Path, *, has_narration: bool = False) -> list[str]:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(list_file)]
    if spec.audio and has_narration:  # musik diulang dan dikecilkan di bawah suara
        cmd += ["-stream_loop", "-1", "-i", str(spec.audio)]
        mix = f"[1:a]volume={MUSIC_VOLUME}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]"
        cmd += ["-filter_complex", mix, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest"]
    elif spec.audio:  # musik diulang agar tidak memotong video bila lebih pendek
        cmd += ["-stream_loop", "-1", "-i", str(spec.audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-c", "copy"]
    return [*cmd, "-movflags", "+faststart", str(out)]


def _narrate(spec: Spec, tts_cfg: TtsConfig | None, tts_error: str, tmp: Path, log) -> tuple[Spec, dict[int, Path]]:
    """Sintesis semua narasi DULU (gagal cepat sebelum render berjam-jam), lalu sesuaikan durasi scene."""
    voices: dict[int, Path] = {}
    if not any(sc.narration for sc in spec.scenes):
        return spec, voices
    if tts_cfg is None:
        raise SpecError(tts_error or "narasi diminta tetapi TTS belum dikonfigurasi (isi TTS_BASE_URL di .env)")
    try:
        tts_cfg = resolve_voice(tts_cfg)  # gagal cepat bila suara tidak ada (server akan diam-diam memakai suara bawaan)
    except TtsError as exc:
        raise SpecError(f"TTS: {exc}") from None
    scenes = list(spec.scenes)
    for i, sc in enumerate(scenes):
        if not sc.narration:
            continue
        log(f"narasi {i + 1}/{len(scenes)}")
        try:
            data = synthesize(tts_cfg, sc.narration)
        except TtsError as exc:
            raise SpecError(f"TTS gagal pada scene {i + 1}: {exc}") from None
        path = tmp / f"voice{i + 1}.audio"
        path.write_bytes(data)
        try:
            dur = audio_duration(path)
        except TtsError as exc:
            raise SpecError(f"scene {i + 1}: {exc}") from None
        scenes[i] = dataclasses.replace(sc, duration=max(sc.duration, round(VOICE_LEAD + dur + VOICE_TAIL, 2)))
        voices[i] = path
    total = sum(s.duration for s in scenes)
    if total > MAX_TOTAL_SECONDS:
        raise SpecError(f"dengan narasi, total durasi {total:.0f} detik melebihi batas {MAX_TOTAL_SECONDS} detik; ringkas narasinya")
    return dataclasses.replace(spec, scenes=tuple(scenes)), voices


def _run_scene(cmd: list[str], spec: Spec, scene: Scene, tmp: Path) -> tuple[int, str]:
    """Jalankan ffmpeg satu scene. Scene bergambar: frame digambar Pillow dan dialirkan lewat stdin."""
    if not scene.draw:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode, r.stderr
    try:
        stage = illustrate.Stage(spec.width, spec.height, scene.color, scene.draw, FONT)
    except illustrate.DrawError as exc:
        raise SpecError(str(exc)) from None
    err_path = tmp / "ffmpeg.err"
    frames = max(1, round(scene.duration * spec.fps))
    with err_path.open("wb") as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err)
        try:
            assert proc.stdin is not None
            for n in range(frames):
                proc.stdin.write(stage.frame(n / spec.fps))
            proc.stdin.close()
        except BrokenPipeError:
            pass  # ffmpeg berhenti lebih awal; pesan kesalahannya ada di stderr
        except Exception:
            proc.kill()
            raise
        finally:
            proc.wait()
    return proc.returncode, err_path.read_text(errors="replace")


def render(spec: Spec, out: Path, *, tts_cfg: TtsConfig | None = None, tts_error: str = "", log=lambda m: print(m, file=sys.stderr, flush=True)) -> None:
    if shutil.which("ffmpeg") is None:
        raise SpecError("ffmpeg tidak terpasang")
    if not Path(FONT).is_file():
        raise SpecError(f"font tidak ditemukan: {FONT} (pasang fonts-dejavu-core)")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clautele-video-") as tmp_s:
        tmp = Path(tmp_s)
        spec, voices = _narrate(spec, tts_cfg, tts_error, tmp, log)
        with_audio = bool(voices)
        segments: list[Path] = []
        for i, scene in enumerate(spec.scenes, 1):
            log(f"scene {i}/{len(spec.scenes)}")
            lines = layout(spec, scene)
            files: list[Path] = []
            for j, ln in enumerate(lines):
                f = tmp / f"s{i}_{j}.txt"
                f.write_text(ln.text, encoding="utf-8")
                files.append(f)
            seg = tmp / f"seg{i:03d}.mp4"
            cmd = scene_command(spec, scene, lines, files, seg, with_audio=with_audio, voice=voices.get(i - 1))
            code, stderr = _run_scene(cmd, spec, scene, tmp)
            if code != 0 or not seg.exists():
                raise SpecError(f"ffmpeg gagal pada scene {i}: {stderr.strip()[-600:]}")
            segments.append(seg)
        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{s}'\n" for s in segments), encoding="utf-8")
        r = subprocess.run(concat_command(listing, spec, out, has_narration=with_audio), capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            raise SpecError(f"ffmpeg gagal menggabung: {r.stderr.strip()[-600:]}")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__ + "\n" + SCHEMA_HELP)
        return 0
    if argv[0] == "--example":
        print(json.dumps(EXAMPLE, indent=2, ensure_ascii=False))
        return 0
    if len(argv) != 2:
        print("Pemakaian: clautele-video SPEC.json HASIL.mp4", file=sys.stderr)
        return 2
    base = Path.cwd()
    try:
        spec_path = Path(argv[0])
        try:
            data = json.loads(spec_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SpecError(f"spec tidak ditemukan: {argv[0]}") from None
        except json.JSONDecodeError as exc:
            raise SpecError(f"JSON tidak valid: {exc}") from None
        spec = parse_spec(data, base_dir=base)
        out = _inside(base, Path(argv[1]), must_exist=False, what="output")
        if out.suffix.lower() != ".mp4":
            raise SpecError("output harus berekstensi .mp4")
        try:
            tts_cfg, tts_error = TtsConfig.from_env(), ""
        except TtsError as exc:
            tts_cfg, tts_error = None, f"konfigurasi TTS salah: {exc}"
        render(spec, out, tts_cfg=tts_cfg, tts_error=tts_error)
    except SpecError as exc:
        print(f"GAGAL: {exc}", file=sys.stderr)
        return 1
    size = out.stat().st_size / (1024 * 1024)
    print(f"OK {out} ({size:.1f} MB, {spec.width}x{spec.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
