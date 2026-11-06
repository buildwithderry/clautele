"""Ilustrasi animasi neon untuk clautele-video: ikon, bentuk, denah, grafik, dan aliran data yang bergerak.

Spec JSON tiap scene boleh punya "draw": [elemen, ...]. Modul ini memvalidasi elemen itu (`parse_elements`) dan
menggambar tiap frame dengan Pillow (`Stage.frame`) sebagai garis neon di atas hitam; pendaran (glow) ditambahkan
ffmpeg di videomaker. Pillow hanya dibutuhkan untuk scene yang memakai "draw".

Koordinat: x,y = 0-100 (% lebar/tinggi panggung); ukuran (size, w, h, r) = % lebar panggung. Titik x,y elemen
adalah PUSAT elemen, kecuali line/arrow/poly yang memakai titik mutlak.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_ELEMENTS = 60
KINDS = ("icon", "rect", "box", "circle", "line", "arrow", "poly", "text", "bars", "floorplan", "chaos")
ANIMS = ("draw", "fade", "pop", "rise", "slide", "type", "none")
LOOPS = ("pulse", "float", "spin", "blink", "rise", "none")
SS = 2  # supersampling: digambar 2x lalu diperkecil agar garis halus

ICON_NAMES = (
    "person", "people", "database", "server", "cloud", "app", "gear", "heart", "building", "lock", "chart",
    "bulb", "check", "globe", "doc", "phone", "star", "mail", "target", "chat", "play",
)  # fmt: skip

DEFAULT_ANIM = {
    "icon": "draw", "rect": "draw", "box": "pop", "circle": "draw", "line": "draw", "arrow": "draw",
    "poly": "draw", "text": "fade", "bars": "draw", "floorplan": "draw", "chaos": "fade",
}  # fmt: skip

SCHEMA_DRAW_HELP = f"""\
"draw": ilustrasi animasi per scene (gambar sesuai konteks: denah, database, server, awan, aplikasi, grafik, alur panah).
  Koordinat x,y = 0-100 (% lebar/tinggi panggung gambar, di bawah judul); x,y adalah PUSAT elemen.
  Ukuran (size, w, h, r) = % lebar panggung. Maks {MAX_ELEMENTS} elemen per scene, digambar berurutan.
  Elemen ("t"):
    icon      {{"t":"icon","name":"database","x":50,"y":40,"size":22,"label":"Data"}}  name: {", ".join(ICON_NAMES)}
    box       {{"t":"box","x":50,"y":30,"w":60,"h":12,"text":"BUSINESS","fill":true}}  kotak berisi teks (pop)
    rect      {{"t":"rect","x":50,"y":50,"w":30,"h":18,"r":2,"fill":false,"text":"opsional"}}
    circle    {{"t":"circle","x":50,"y":50,"r":8,"text":"opsional"}}
    line      {{"t":"line","x1":10,"y1":50,"x2":90,"y2":50,"dots":true}}   dots = titik cahaya mengalir di garis
    arrow     {{"t":"arrow","x1":30,"y1":50,"x2":70,"y2":50,"dots":true}}
    poly      {{"t":"poly","points":[[10,80],[40,50],[70,60],[90,20]],"closed":false,"dots":true}}  garis patah/bentuk bebas
    text      {{"t":"text","x":50,"y":90,"text":"Halo","size":4.5,"anim":"type"}}
    bars      {{"t":"bars","x":50,"y":55,"w":60,"h":40,"values":[3,5,8,13],"labels":["Q1","Q2","Q3","Q4"]}}  batang tumbuh
    floorplan {{"t":"floorplan","x":50,"y":50,"size":80,"labels":["Ruang Tamu","Dapur","Kamar","KM"]}}  denah rumah tergambar pelan
    chaos     {{"t":"chaos","x":50,"y":50,"w":70,"h":40,"count":14,"settle":2,"color2":"green"}}  kotak berantakan lalu rapi
  Opsi umum: "color" (nama/#RRGGBB, default warna scene), "at" (detik mulai, default 0), "dur" (lama animasi masuk),
    "anim": draw (garis tergambar) | fade | pop (membesar) | rise (naik) | slide (dari kiri) | type (diketik) | none,
    "loop": pulse (berdenyut) | float (melayang) | spin (berputar, cocok gear) | blink | rise (naik berulang, cocok heart) | none,
    "width": tebal garis (0.3-4, default 1).
  Susun cerita lewat "at": mis. denah at 0, panah at 2, ikon at 3. Tiap scene sebaiknya punya 3-8 elemen yang saling berkaitan.
"""


class DrawError(ValueError):
    """Elemen draw tidak valid; pesan aman ditampilkan ke user/Claude."""


@dataclass(frozen=True)
class Element:
    kind: str
    p: dict[str, Any] = field(default_factory=dict)


# ---------- validasi ----------


def _num(raw: dict[str, Any], key: str, lo: float, hi: float, default: float | None, where: str) -> float | None:
    if key not in raw or raw[key] is None:
        return default
    v = raw[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        raise DrawError(f"{where}: {key} harus angka")
    if not lo <= v <= hi:
        raise DrawError(f"{where}: {key} harus {lo:g}-{hi:g} (nilai {v:g})")
    return float(v)


def _str(raw: dict[str, Any], key: str, limit: int, where: str) -> str:
    v = raw.get(key, "")
    if v is None:
        return ""
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise DrawError(f"{where}: {key} harus teks")
    s = " ".join(str(v).split())
    if len(s) > limit:
        raise DrawError(f"{where}: {key} terlalu panjang ({len(s)} > {limit} karakter)")
    return s


def parse_elements(raw: Any, scene_no: int, resolve_color: Callable[[Any], str]) -> tuple[Element, ...]:
    if raw is None or raw == []:
        return ()
    if not isinstance(raw, list):
        raise DrawError(f"scene {scene_no}: draw harus berupa daftar elemen")
    if len(raw) > MAX_ELEMENTS:
        raise DrawError(f"scene {scene_no}: draw maksimal {MAX_ELEMENTS} elemen")
    out: list[Element] = []
    for n, e in enumerate(raw, 1):
        where = f"scene {scene_no} draw {n}"
        if not isinstance(e, dict):
            raise DrawError(f"{where}: harus berupa objek")
        kind = e.get("t")
        if kind not in KINDS:
            raise DrawError(f"{where}: t '{kind}' tidak dikenal (pakai {', '.join(KINDS)})")
        p: dict[str, Any] = {}
        p["x"] = _num(e, "x", -20, 120, 50, where)
        p["y"] = _num(e, "y", -20, 120, 50, where)
        p["at"] = _num(e, "at", 0, 60, 0, where)
        p["dur"] = _num(e, "dur", 0.1, 20, 2.2 if kind == "floorplan" else 0.9, where)
        p["width"] = _num(e, "width", 0.3, 4, 1, where)
        anim = e.get("anim", DEFAULT_ANIM[kind])
        loop = e.get("loop", "none")
        if anim not in ANIMS:
            raise DrawError(f"{where}: anim '{anim}' tidak dikenal (pakai {', '.join(ANIMS)})")
        if loop not in LOOPS:
            raise DrawError(f"{where}: loop '{loop}' tidak dikenal (pakai {', '.join(LOOPS)})")
        p["anim"], p["loop"] = anim, loop
        p["color"] = resolve_color(e["color"]) if e.get("color") else None
        p["text"] = _str(e, "text", 60, where)
        p["label"] = _str(e, "label", 40, where)
        p["fill"] = e.get("fill")
        if p["fill"] is not None and not isinstance(p["fill"], bool):
            raise DrawError(f"{where}: fill harus true/false")
        p["dots"] = bool(e.get("dots", False))
        if kind == "icon":
            name = e.get("name")
            if name not in ICON_NAMES:
                raise DrawError(f"{where}: name '{name}' tidak dikenal (pakai {', '.join(ICON_NAMES)})")
            p["name"] = name
            p["size"] = _num(e, "size", 3, 120, 22, where)
        elif kind in ("rect", "box"):
            p["w"] = _num(e, "w", 1, 200, 30 if kind == "rect" else 40, where)
            p["h"] = _num(e, "h", 1, 200, 18 if kind == "rect" else 12, where)
            p["r"] = _num(e, "r", 0, 60, 2, where)
            if kind == "box" and p["fill"] is None:
                p["fill"] = True
        elif kind == "circle":
            p["r"] = _num(e, "r", 1, 100, 8, where)
        elif kind in ("line", "arrow"):
            for k, d in (("x1", 20), ("y1", 50), ("x2", 80), ("y2", 50)):
                p[k] = _num(e, k, -20, 120, d, where)
        elif kind == "poly":
            pts = e.get("points")
            if not isinstance(pts, list) or not 2 <= len(pts) <= 40:
                raise DrawError(f"{where}: points harus daftar 2-40 titik [[x,y],...]")
            clean = []
            for pt in pts:
                if (
                    not isinstance(pt, (list, tuple)) or len(pt) != 2
                    or any(isinstance(c, bool) or not isinstance(c, (int, float)) or not -20 <= c <= 120 for c in pt)
                ):  # fmt: skip
                    raise DrawError(f"{where}: tiap titik harus [x,y] berisi angka -20..120")
                clean.append((float(pt[0]), float(pt[1])))
            p["points"] = clean
            p["closed"] = bool(e.get("closed", False))
        elif kind == "text":
            if not p["text"]:
                raise DrawError(f"{where}: text wajib diisi")
            p["size"] = _num(e, "size", 1, 20, 4.5, where)
        elif kind == "bars":
            vals = e.get("values")
            if (
                not isinstance(vals, list) or not 1 <= len(vals) <= 12
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 for v in vals)
            ):  # fmt: skip
                raise DrawError(f"{where}: values harus daftar 1-12 angka >= 0")
            p["values"] = [float(v) for v in vals]
            labels = e.get("labels", [])
            if not isinstance(labels, list) or len(labels) > 12 or any(not isinstance(s, (str, int, float)) for s in labels):
                raise DrawError(f"{where}: labels harus daftar teks (maks 12)")
            p["labels"] = [" ".join(str(s).split())[:14] for s in labels]
            p["w"] = _num(e, "w", 5, 200, 60, where)
            p["h"] = _num(e, "h", 5, 200, 40, where)
        elif kind == "floorplan":
            p["size"] = _num(e, "size", 20, 150, 80, where)
            labels = e.get("labels", [])
            if not isinstance(labels, list) or len(labels) > 4 or any(not isinstance(s, (str, int, float)) for s in labels):
                raise DrawError(f"{where}: labels denah harus daftar maks 4 teks")
            p["labels"] = [" ".join(str(s).split())[:14] for s in labels]
        elif kind == "chaos":
            p["w"] = _num(e, "w", 10, 200, 70, where)
            p["h"] = _num(e, "h", 10, 200, 40, where)
            p["count"] = int(_num(e, "count", 3, 40, 14, where))
            p["settle"] = _num(e, "settle", 0, 30, 2, where)
            p["color2"] = resolve_color(e["color2"]) if e.get("color2") else None
        out.append(Element(kind, p))
    return tuple(out)


def stage_rect(width: int, height: int) -> tuple[int, int, int, int]:
    """Kotak panggung gambar (x, y, w, h) di bawah blok judul; selalu genap."""
    if width > height:  # landscape: judul tipis di atas
        x, y, b = int(width * 0.10), int(height * 0.25), int(height * 0.86)
    else:
        x, y, b = int(width * 0.07), int(height * 0.27), int(height * 0.88)
    w, h = width - 2 * x, b - y
    return x - x % 2, y - y % 2, w - w % 2, h - h % 2


def title_reserve(width: int, height: int) -> float:
    """Pecahan tinggi kanvas yang dipakai blok judul bila scene punya gambar."""
    return 0.25 if width > height else 0.27


# ---------- geometri ----------

Pt = tuple[float, float]
RGB = tuple[int, int, int]


@dataclass
class Shape:
    pts: list[Pt]
    closed: bool = False
    fill: bool = False
    color: RGB | None = None


@dataclass
class Label:
    text: str
    x: float
    y: float
    size: float
    max_w: float = 0.0


@dataclass
class Built:
    shapes: list[Shape] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    path: list[Pt] | None = None  # jalur titik cahaya
    own_progress: bool = False  # bentuk sudah menangani animasinya sendiri (bars, chaos)


def arc(cx: float, cy: float, r: float, a0: float, a1: float, n: int = 24, ry: float | None = None) -> list[Pt]:
    ry = r if ry is None else ry
    return [
        (cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
        for i in range(n + 1)
    ]


def ell(cx: float, cy: float, rx: float, ry: float | None = None, n: int = 40) -> list[Pt]:
    return arc(cx, cy, rx, 0, 360, n, ry)[:-1]


def rrect(cx: float, cy: float, w: float, h: float, r: float) -> list[Pt]:
    r = max(0.0, min(r, w / 2, h / 2))
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    if r < 0.5:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return arc(x1 - r, y0 + r, r, -90, 0, 5) + arc(x1 - r, y1 - r, r, 0, 90, 5) + arc(x0 + r, y1 - r, r, 90, 180, 5) + arc(x0 + r, y0 + r, r, 180, 270, 5)


def _S(pts: list[Pt], closed: bool = False, fill: bool = False) -> Shape:
    return Shape(pts, closed, fill)


def _person(sx: float = 1.0, dx: float = 0.0, dy: float = 0.0) -> list[Shape]:
    head = [(dx + x * sx, dy + y * sx) for x, y in ell(0, -0.45, 0.28)]
    body = [(dx + x * sx, dy + y * sx) for x, y in arc(0, 0.95, 0.72, 180, 360, 20)]
    return [_S(head, True, True), _S(body, True, True)]


def _star() -> list[Pt]:
    pts = []
    for i in range(10):
        r = 0.95 if i % 2 == 0 else 0.4
        a = math.radians(-90 + i * 36)
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def _gear() -> list[Shape]:
    pts: list[Pt] = []
    teeth = 8
    for i in range(teeth):
        base = i * 2 * math.pi / teeth
        for da, r in ((-0.20, 0.72), (-0.12, 0.96), (0.12, 0.96), (0.20, 0.72)):
            a = base + da
            pts.append((r * math.cos(a), r * math.sin(a)))
    return [_S(pts, True, True), _S(ell(0, 0, 0.3), True)]


def _heart() -> list[Pt]:
    pts = []
    for i in range(60):
        t = 2 * math.pi * i / 60
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((x / 17.5, y / 17.5 + 0.05))
    return pts


def _cloud() -> list[Pt]:
    pts = [(-0.5, 0.45), (0.6, 0.45)]
    pts += arc(0.6, 0.15, 0.3, 90, -90, 10)
    pts += arc(0.12, -0.15, 0.48, 0, -150, 18)
    pts += arc(-0.5, 0.0, 0.45, -62, -270, 18)
    return pts


def _icon_shapes(name: str) -> list[Shape]:
    if name == "person":
        return _person()
    if name == "people":
        return _person(0.62, -0.62, 0.25) + _person(0.62, 0.62, 0.25) + _person(0.85, 0.0, 0.05)
    if name == "database":
        return [
            _S(ell(0, -0.65, 0.7, 0.22), True, True),
            _S([(-0.7, -0.65), (-0.7, 0.65)]), _S([(0.7, -0.65), (0.7, 0.65)]),
            _S(arc(0, -0.2, 0.7, 0, 180, 20, 0.22)), _S(arc(0, 0.22, 0.7, 0, 180, 20, 0.22)),
            _S(arc(0, 0.65, 0.7, 0, 180, 20, 0.22)),
        ]  # fmt: skip
    if name == "server":
        out: list[Shape] = []
        for y in (-0.62, 0.0, 0.62):
            out += [_S(rrect(0, y, 1.8, 0.5, 0.08), True, True), _S(ell(-0.6, y, 0.07, 0.07, 12), True), _S([(-0.1, y), (0.6, y)])]
        return out
    if name == "cloud":
        return [_S(_cloud(), True, True)]
    if name == "app":
        return [
            _S(rrect(0, 0, 1.8, 1.45, 0.12), True, True), _S([(-0.9, -0.4), (0.9, -0.4)]),
            *[_S(ell(x, -0.57, 0.06, 0.06, 10), True) for x in (-0.72, -0.55, -0.38)],
            _S([(-0.7, -0.1), (0.3, -0.1)]), _S([(-0.7, 0.15), (0.5, 0.15)]), _S([(-0.7, 0.4), (0.0, 0.4)]),
            _S(rrect(0.45, 0.38, 0.4, 0.28, 0.05), True),
        ]  # fmt: skip
    if name == "gear":
        return _gear()
    if name == "heart":
        return [_S(_heart(), True, True)]
    if name == "building":
        out = [_S([(-0.55, 0.95), (-0.55, -0.95), (0.55, -0.95), (0.55, 0.95)], False, True), _S([(-0.8, 0.95), (0.8, 0.95)])]
        for r in range(4):
            for c in (-0.25, 0.25):
                out.append(_S(rrect(c, -0.65 + r * 0.38, 0.22, 0.2, 0.0), True))
        out.append(_S([(-0.1, 0.95), (-0.1, 0.6), (0.1, 0.6), (0.1, 0.95)]))
        return out
    if name == "lock":
        return [
            _S([(-0.45, -0.2)] + arc(0, -0.25, 0.45, 180, 360, 16) + [(0.45, -0.2)]),
            _S(rrect(0, 0.3, 1.4, 1.0, 0.1), True, True), _S(ell(0, 0.28, 0.12, 0.12, 14), True), _S([(0, 0.4), (0, 0.6)]),
        ]  # fmt: skip
    if name == "chart":
        bars = [(-0.6, 0.5), (-0.2, 0.9), (0.2, 1.3), (0.6, 1.7)]
        return [_S([(-0.9, -0.9), (-0.9, 0.9), (0.9, 0.9)])] + [
            _S([(x - 0.12, 0.9), (x - 0.12, 0.9 - h), (x + 0.12, 0.9 - h), (x + 0.12, 0.9)], False, True) for x, h in bars
        ]
    if name == "bulb":
        return [
            _S(arc(0, -0.25, 0.6, 120, 420, 28) + [(0.25, 0.6), (-0.25, 0.6)], True, True),
            _S([(-0.22, 0.75), (0.22, 0.75)]), _S([(-0.15, 0.9), (0.15, 0.9)]),
        ]  # fmt: skip
    if name == "check":
        return [_S(ell(0, 0, 0.85), True, True), _S([(-0.4, 0.0), (-0.1, 0.3), (0.45, -0.3)])]
    if name == "globe":
        return [
            _S(ell(0, 0, 0.85), True, True), _S(ell(0, 0, 0.35, 0.85)), _S([(-0.85, 0), (0.85, 0)]),
            _S([(-0.72, -0.45), (0.72, -0.45)]), _S([(-0.72, 0.45), (0.72, 0.45)]),
        ]  # fmt: skip
    if name == "doc":
        return [
            _S([(-0.6, -0.9), (0.2, -0.9), (0.6, -0.5), (0.6, 0.9), (-0.6, 0.9)], True, True),
            _S([(0.2, -0.9), (0.2, -0.5), (0.6, -0.5)]),
            *[_S([(-0.35, y), (0.35, y)]) for y in (-0.1, 0.2, 0.5)],
        ]  # fmt: skip
    if name == "phone":
        return [_S(rrect(0, 0, 1.0, 1.8, 0.15), True, True), _S([(-0.15, -0.76), (0.15, -0.76)]), _S(ell(0, 0.74, 0.08, 0.08, 10), True)]
    if name == "star":
        return [_S(_star(), True, True)]
    if name == "mail":
        return [_S(rrect(0, 0, 1.8, 1.2, 0.08), True, True), _S([(-0.9, -0.6), (0, 0.1), (0.9, -0.6)])]
    if name == "target":
        return [_S(ell(0, 0, 0.9), True), _S(ell(0, 0, 0.6), True), _S(ell(0, 0, 0.3), True, True), _S([(0, 0), (0.7, -0.7)])]
    if name == "chat":
        return [_S(rrect(0, -0.1, 1.7, 1.1, 0.25), True, True), _S([(-0.4, 0.45), (-0.6, 0.85), (-0.1, 0.45)]), _S([(-0.5, -0.2), (0.5, -0.2)]), _S([(-0.5, 0.05), (0.2, 0.05)])]
    if name == "play":
        return [_S(ell(0, 0, 0.9), True, True), _S([(-0.25, -0.4), (0.45, 0), (-0.25, 0.4)], True)]
    raise DrawError(f"ikon '{name}' tidak dikenal")


def _scaled(shapes: list[Shape], k: float) -> list[Shape]:
    return [Shape([(x * k, y * k) for x, y in s.pts], s.closed, s.fill, s.color) for s in shapes]


def _floorplan(k: float) -> tuple[list[Shape], list[Label]]:
    """Denah rumah dalam koordinat 0-100 x 0-70, digambar berurutan: dinding, pintu, jendela, perabot, ukuran."""
    X = lambda x: (x - 50) * k  # noqa: E731
    Y = lambda y: (y - 35) * k  # noqa: E731
    P = lambda pts, closed=False, fill=False: Shape([(X(x), Y(y)) for x, y in pts], closed, fill)  # noqa: E731
    walls = [
        P([(18, 70), (0, 70), (0, 0), (100, 0), (100, 70), (30, 70)]),
        P([(58, 0), (58, 10)]), P([(58, 22), (58, 44)]), P([(58, 56), (58, 70)]),
        P([(58, 32), (100, 32)]), P([(82, 32), (82, 55)]), P([(82, 65), (82, 70)]),
    ]  # fmt: skip
    doors = [
        P([(58, 10), (70, 10)]), P(arc(58, 10, 12, 0, 90, 10)),
        P([(58, 44), (70, 44)]), P(arc(58, 44, 12, 0, 90, 10)),
        P([(82, 55), (92, 55)]), P(arc(82, 55, 10, 0, 90, 8)),
        P([(18, 70), (18, 58)]), P(arc(18, 70, 12, -90, 0, 10)),
    ]  # fmt: skip
    windows = [
        P([(12, -1.8), (32, -1.8), (32, 1.8), (12, 1.8)], True, True),
        P([(66, -1.8), (90, -1.8), (90, 1.8), (66, 1.8)], True, True),
        P([(-1.8, 18), (1.8, 18), (1.8, 42), (-1.8, 42)], True, True),
        P([(98.2, 40), (101.8, 40), (101.8, 58), (98.2, 58)], True, True),
        P([(40, 68.2), (54, 68.2), (54, 71.8), (40, 71.8)], True, True),
    ]  # fmt: skip
    furniture = [
        P(rrect(28, 9, 24, 9, 3), True, True),  # sofa
        P(ell(38, 36, 7, 7, 24), True, True),  # meja makan
        *[P(ell(x, y, 2, 2, 10), True) for x, y in ((38, 26), (38, 46), (27, 36), (49, 36))],
        P(rrect(80, 5, 36, 7, 1), True, True), P(ell(74, 5, 1.8, 1.8, 10), True), P(ell(82, 5, 1.8, 1.8, 10), True),
        P(rrect(82, 22, 14, 6, 1), True, True),  # dapur
        P(rrect(73, 60, 14, 18, 1.5), True, True), P(rrect(73, 53, 12, 4, 1), True),  # kamar tidur
        P(rrect(91, 39.5, 14, 11, 4), True, True), P(ell(96, 58, 2.4, 2.4, 10), True), P(ell(96, 65, 2.6, 2.6, 10), True),  # kamar mandi
    ]  # fmt: skip
    dims = [
        P([(0, 77), (100, 77)]), P([(0, 74), (0, 80)]), P([(100, 74), (100, 80)]),
        P([(-7, 0), (-7, 70)]), P([(-10, 0), (-4, 0)]), P([(-10, 70), (-4, 70)]),
    ]  # fmt: skip
    return walls + doors + windows + furniture + dims, []


def _room_labels(k: float, names: list[str]) -> list[Label]:
    spots = [(20, 22, 24), (88, 14, 22), (70, 40, 20), (88.5, 51, 11)]
    return [Label(n, (x - 50) * k, (y - 35) * k, 4.2 * k, w * k) for n, (x, y, w) in zip(names, spots) if n]


# ---------- pewarnaan ----------


def hex_rgb(h: str) -> RGB:
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _dim(c: RGB, a: float) -> RGB:
    return int(c[0] * a), int(c[1] * a), int(c[2] * a)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def _ease(p: float) -> float:
    p = _clamp(p)
    return 1 - (1 - p) ** 3


def _ease_io(p: float) -> float:
    p = _clamp(p)
    return 3 * p * p - 2 * p * p * p


def _ease_back(p: float) -> float:
    p = _clamp(p)
    c1 = 1.9
    return 1 + (c1 + 1) * (p - 1) ** 3 + c1 * (p - 1) ** 2


def _path_len(pts: list[Pt], closed: bool) -> float:
    seq = pts + [pts[0]] if closed and pts else pts
    return sum(math.dist(seq[i], seq[i + 1]) for i in range(len(seq) - 1))


def _partial(pts: list[Pt], closed: bool, length: float) -> list[Pt]:
    """Titik-titik jalur sampai sepanjang `length` piksel."""
    seq = pts + [pts[0]] if closed and pts else list(pts)
    out = [seq[0]]
    left = length
    for i in range(len(seq) - 1):
        seg = math.dist(seq[i], seq[i + 1])
        if seg <= left:
            out.append(seq[i + 1])
            left -= seg
        else:
            f = left / seg if seg else 0
            out.append((seq[i][0] + (seq[i + 1][0] - seq[i][0]) * f, seq[i][1] + (seq[i + 1][1] - seq[i][1]) * f))
            break
    return out


def _point_at(pts: list[Pt], f: float) -> Pt:
    total = _path_len(pts, False)
    if total <= 0:
        return pts[0]
    return _partial(pts, False, total * f)[-1]


# ---------- panggung ----------


class Stage:
    """Menggambar frame ilustrasi (RGB hitam + garis neon) berukuran panggung."""

    def __init__(self, width: int, height: int, scene_color: str, elements: tuple[Element, ...], font_path: str) -> None:
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415
        except ImportError:
            raise DrawError("Pillow belum terpasang (pip install Pillow) — dibutuhkan untuk scene dengan draw") from None
        self._Image, self._ImageDraw, self._ImageFont = Image, ImageDraw, ImageFont
        self.font_path = font_path
        _, _, self.sw, self.sh = stage_rect(width, height)
        self.W, self.H = self.sw * SS, self.sh * SS
        self.U = self.W / 100.0
        self.color = hex_rgb(scene_color)
        self.elements = elements
        self.stroke = max(2.0, self.W / 230.0)
        self._fonts: dict[int, Any] = {}
        rnd = random.Random(11)
        self._sparks = [(rnd.random(), rnd.random(), 0.04 + rnd.random() * 0.08, rnd.random() * 6.28) for _ in range(22)]

    # --- primitif gambar ---
    def _font(self, size: float):
        s = max(8, int(size))
        f = self._fonts.get(s)
        if f is None:
            f = self._fonts[s] = self._ImageFont.truetype(self.font_path, s)
        return f

    def _fit_font(self, text: str, size: float, max_w: float):
        s = int(size)
        while s > 8 and self._font(s).getlength(text) > max_w > 0:
            s -= 2
        return self._font(s)

    def _stroke(self, d, pts: list[Pt], closed: bool, color: RGB, width: float) -> None:
        if len(pts) < 2:
            return
        seq = pts + [pts[0]] if closed else pts
        w = max(1, int(round(width)))
        d.line(seq, fill=color, width=w, joint="curve")
        r = w / 2.0
        for x, y in (seq[0], seq[-1]):
            d.ellipse((x - r, y - r, x + r, y + r), fill=color)

    def _neon(self, d, pts: list[Pt], closed: bool, color: RGB, alpha: float, wmul: float) -> None:
        w = self.stroke * wmul
        self._stroke(d, pts, closed, _dim(color, alpha), w)
        self._stroke(d, pts, closed, _dim(_mix(color, (255, 255, 255), 0.62), alpha), max(1.0, w * 0.38))

    def _dot(self, d, x: float, y: float, r: float, color: RGB, alpha: float) -> None:
        d.ellipse((x - r, y - r, x + r, y + r), fill=_dim(color, alpha))
        r2 = r * 0.5
        d.ellipse((x - r2, y - r2, x + r2, y + r2), fill=_dim(_mix(color, (255, 255, 255), 0.7), alpha))

    # --- pembangun bentuk ---
    def _build(self, el: Element, p: float, tt: float) -> tuple[Built, Pt]:
        U, W, H = self.U, self.W, self.H
        q = el.p
        cx, cy = q["x"] / 100 * W, q["y"] / 100 * H
        kind = el.kind
        b = Built()
        if kind == "icon":
            k = q["size"] / 2 * U
            b.shapes = _scaled(_icon_shapes(q["name"]), k)
            if q["fill"] is False:
                for s in b.shapes:
                    s.fill = False
            if q["label"]:
                b.labels.append(Label(q["label"], 0, k + 3.4 * U, 3.4 * U, 36 * U))
        elif kind in ("rect", "box"):
            b.shapes = [Shape(rrect(0, 0, q["w"] * U, q["h"] * U, q["r"] * U), True, bool(q["fill"]))]
            if q["text"]:
                b.labels.append(Label(q["text"], 0, 0, min(q["h"] * U * 0.42, 5 * U), q["w"] * U * 0.9))
        elif kind == "circle":
            b.shapes = [Shape(ell(0, 0, q["r"] * U), True, bool(q["fill"]))]
            if q["text"]:
                b.labels.append(Label(q["text"], 0, 0, min(q["r"] * U * 0.5, 4.5 * U), q["r"] * U * 1.7))
        elif kind in ("line", "arrow", "poly"):
            if kind == "poly":
                pts = [(x / 100 * W, y / 100 * H) for x, y in q["points"]]
            else:
                pts = [(q["x1"] / 100 * W, q["y1"] / 100 * H), (q["x2"] / 100 * W, q["y2"] / 100 * H)]
            xs, ys = [a for a, _ in pts], [c for _, c in pts]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            rel = [(a - cx, c - cy) for a, c in pts]
            b.shapes = [Shape(rel, el.kind == "poly" and q["closed"], bool(q["fill"]) and el.kind == "poly")]
            b.path = rel
            if kind == "arrow" and math.dist(rel[0], rel[1]) > 0:
                (x0, y0), (x1, y1) = rel[-2], rel[-1]
                ang = math.atan2(y1 - y0, x1 - x0)
                hl = 3.2 * U
                b.shapes.append(
                    Shape([(x1 - hl * math.cos(ang - 0.45), y1 - hl * math.sin(ang - 0.45)), (x1, y1),
                           (x1 - hl * math.cos(ang + 0.45), y1 - hl * math.sin(ang + 0.45))])
                )  # fmt: skip
        elif kind == "text":
            txt = q["text"]
            if q["anim"] == "type":
                txt = txt[: int(len(txt) * _clamp(p) + 0.999)]
            b.labels.append(Label(txt, 0, 0, q["size"] * U, 96 * U))
        elif kind == "bars":
            vals, n = q["values"], len(q["values"])
            w, h = q["w"] * U, q["h"] * U
            top = max(vals) or 1.0
            slot = w / n
            bw = slot * 0.62
            base = h / 2
            b.shapes.append(Shape([(-w / 2 - slot * 0.1, -h / 2), (-w / 2 - slot * 0.1, base), (w / 2, base)]))
            for i, v in enumerate(vals):
                grow = _ease(_clamp((p - i / (n + 1) * 0.6) / 0.4))
                bh = max(1.0, (h * 0.92) * v / top * grow)
                x = -w / 2 + slot * (i + 0.5)
                b.shapes.append(Shape([(x - bw / 2, base), (x - bw / 2, base - bh), (x + bw / 2, base - bh), (x + bw / 2, base)], False, True))
                if i < len(q["labels"]) and q["labels"][i]:
                    b.labels.append(Label(q["labels"][i], x, base + 3 * U, 2.8 * U, slot * 0.95))
            b.own_progress = True
        elif kind == "floorplan":
            k = q["size"] * U / 100
            b.shapes, _ = _floorplan(k)
            b.labels = _room_labels(k, q["labels"])
        elif kind == "chaos":
            self._chaos(b, q, tt)
        return b, (cx, cy)

    def _chaos(self, b: Built, q: dict[str, Any], tt: float) -> None:
        U = self.U
        n, w, h = q["count"], q["w"] * U, q["h"] * U
        rnd = random.Random(n * 31 + 7)
        cols = max(1, round(math.sqrt(n * w / h)))
        rows = math.ceil(n / cols)
        cw, ch = w / cols, h / rows
        sz = min(cw, ch) * 0.62
        e = _ease_io(_clamp((tt - q["settle"]) / 1.3))
        c1 = None
        if q["color2"]:
            c1 = _mix(hex_rgb(q["color"]) if q["color"] else self.color, hex_rgb(q["color2"]), e)
        for i in range(n):
            x0, y0 = rnd.uniform(-w / 2, w / 2), rnd.uniform(-h / 2, h / 2)
            r0, s0 = rnd.uniform(0, math.pi), rnd.uniform(0.6, 1.5) * sz
            jit = (1 - e) * U * 0.9
            jx, jy = math.sin(tt * 9 + i * 2.1) * jit, math.cos(tt * 8 + i * 1.3) * jit
            gx, gy = -w / 2 + cw * (i % cols + 0.5), -h / 2 + ch * (i // cols + 0.5)
            x, y = x0 + jx + (gx - x0 - jx) * e, y0 + jy + (gy - y0 - jy) * e
            rot = (r0 + math.sin(tt * 5 + i) * 0.15) * (1 - e)
            s = (s0 + (sz - s0) * e) / 2
            c, sn = math.cos(rot), math.sin(rot)
            pts = [(x + (px * c - py * sn), y + (px * sn + py * c)) for px, py in ((-s, -s), (s, -s), (s, s), (-s, s))]
            b.shapes.append(Shape(pts, True, True, c1))
        b.own_progress = True

    # --- satu elemen ---
    def _draw_element(self, d, el: Element, t: float) -> None:
        q = el.p
        if t < q["at"]:
            return
        tt = t - q["at"]
        p = _clamp(tt / q["dur"])
        anim, loop = q["anim"], q["loop"]
        U = self.U
        built, (ax, ay) = self._build(el, p, tt)
        color = hex_rgb(q["color"]) if q["color"] else self.color
        scale, alpha, dx, dy, rot = 1.0, 1.0, 0.0, 0.0, 0.0
        label_alpha = 1.0
        prog = 1.0
        if anim == "draw" and not built.own_progress and el.kind != "text":
            prog = _ease_io(p)
            alpha = 1.0
            label_alpha = _clamp((p - 0.6) / 0.4)
        elif anim == "pop":
            scale = max(0.001, _ease_back(p))
            alpha = _clamp(p * 4)
        elif anim == "slide":
            dx, alpha = -(1 - _ease(p)) * 18 * U, _ease(p)
        elif anim == "rise":
            dy, alpha = (1 - _ease(p)) * 10 * U, _ease(p)
        elif anim in ("fade", "type", "draw"):
            alpha = _ease(p) if anim != "type" else 1.0
        # "none": langsung tampil penuh
        if built.own_progress and anim == "draw":
            alpha = 1.0
        if loop == "pulse":
            scale *= 1 + 0.07 * math.sin(2 * math.pi * 0.8 * tt)
        elif loop == "float":
            dy += math.sin(2 * math.pi * 0.5 * tt) * 1.6 * U
        elif loop == "spin":
            rot = tt * 0.9
        elif loop == "blink":
            alpha *= 0.45 + 0.55 * abs(math.sin(2 * math.pi * 0.6 * tt))
        elif loop == "rise":
            ph = (tt / 2.4) % 1.0
            dy -= ph * 16 * U
            alpha *= math.sin(math.pi * ph)
        if alpha <= 0.01:
            return
        cr, sr = math.cos(rot), math.sin(rot)
        ox, oy = ax + dx, ay + dy

        def tf(pt: Pt) -> Pt:
            x, y = pt[0] * scale, pt[1] * scale
            return ox + x * cr - y * sr, oy + x * sr + y * cr

        wmul = q["width"]
        # isi redup dulu agar garis neon tetap di atasnya
        fill_a = alpha * (_clamp((p - 0.5) / 0.5) if anim == "draw" and not built.own_progress else 1.0)
        for s in built.shapes:
            if s.fill and q["fill"] is not False and len(s.pts) >= 3 and fill_a > 0.02:
                d.polygon([tf(pt) for pt in s.pts], fill=_dim(s.color or color, 0.16 * fill_a))
        tpts = [[tf(pt) for pt in s.pts] for s in built.shapes]
        budget = sum(_path_len(pp, s.closed) for pp, s in zip(tpts, built.shapes)) * prog
        for s, pts in zip(built.shapes, tpts):
            c = s.color or color
            if prog >= 1:
                self._neon(d, pts, s.closed, c, alpha, wmul)
                continue
            seg = _path_len(pts, s.closed)
            if budget <= 0:
                break
            part = _partial(pts, s.closed, min(budget, seg))
            self._neon(d, part, False, c, alpha, wmul)
            if budget < seg:
                x, y = part[-1]  # ujung pena yang sedang menggambar
                self._dot(d, x, y, self.stroke * 1.5, c, alpha)
                break
            budget -= seg
        # titik cahaya mengalir di garis/panah
        if q["dots"] and built.path and p >= 0.95 and len(built.path) >= 2:
            route = [tf(pt) for pt in built.path]
            for i in range(3):
                x, y = _point_at(route, ((tt * 0.45) + i / 3) % 1.0)
                self._dot(d, x, y, self.stroke * 1.7, color, alpha)
        la = alpha * label_alpha
        if la > 0.02:
            for lb in built.labels:
                font = self._fit_font(lb.text, lb.size * scale, lb.max_w * scale)
                x, y = ox + lb.x * scale, oy + lb.y * scale
                d.text((x, y), lb.text, font=font, fill=_dim(_mix(color, (255, 255, 255), 0.45), la), anchor="mm")

    def _ambient(self, d, t: float) -> None:
        for fx, fy, sp, ph in self._sparks:
            y = (fy - t * sp) % 1.0
            x = fx + math.sin(t * 0.7 + ph) * 0.015
            a = 0.18 + 0.17 * math.sin(t * 1.6 + ph)
            r = self.stroke * 0.55
            d.ellipse((x * self.W - r, y * self.H - r, x * self.W + r, y * self.H + r), fill=_dim(self.color, max(0.0, a)))

    def frame(self, t: float) -> bytes:
        img = self._Image.new("RGB", (self.W, self.H), (0, 0, 0))
        d = self._ImageDraw.Draw(img)
        self._ambient(d, t)
        for el in self.elements:
            self._draw_element(d, el, t)
        return img.reduce(SS).tobytes()

    def image(self, t: float):
        """Satu frame sebagai gambar PIL (untuk pratinjau/uji)."""
        return self._Image.frombytes("RGB", (self.sw, self.sh), self.frame(t))
