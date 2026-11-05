"""Klien TTS generik untuk endpoint kompatibel OpenAI (POST /v1/audio/speech), mis. VoiceStudio di mesin lain.

Hanya stdlib. Pengaman: HTTPS wajib kecuali loopback; redirect ditolak (kredensial tidak boleh ikut ke host
lain); ukuran respons dibatasi; isi balasan diperiksa benar-benar audio; kredensial tidak pernah masuk ke pesan error.

    python -m clautele.tts --probe            # diagnosis: health, engine, daftar path API, uji sintesis
    python -m clautele.tts "Halo dunia" out.wav
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

MAX_TEXT_CHARS = 600
MAX_RESPONSE_BYTES = 40 * 1024 * 1024
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
AUDIO_MAGIC = (b"RIFF", b"ID3", b"OggS", b"fLaC", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")


class TtsError(RuntimeError):
    """Kegagalan TTS. Pesannya aman ditampilkan (tidak memuat kredensial)."""


@dataclass(frozen=True)
class TtsConfig:
    base_url: str
    model: str = "tts-1"
    voice: str = "default"
    response_format: str = "wav"
    language: str | None = None
    timeout: int = 120
    headers: dict[str, str] = field(default_factory=dict, repr=False)  # berisi kredensial: jangan di-print

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "TtsConfig | None":
        e = os.environ if env is None else env
        base = e.get("TTS_BASE_URL", "").strip().rstrip("/")
        if not base:
            return None
        u = urlparse(base)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise TtsError("TTS_BASE_URL harus berupa URL http(s) yang valid")
        if u.scheme == "http" and u.hostname not in LOOPBACK:
            raise TtsError("TTS_BASE_URL harus https:// (http hanya untuk localhost); kredensial tidak boleh lewat plaintext")
        if u.username or u.password:
            raise TtsError("jangan taruh user:password di URL; pakai TTS_BASIC_AUTH")

        headers: dict[str, str] = {"ngrok-skip-browser-warning": "1"}  # tunnel ngrok gratis menyisipkan halaman peringatan
        basic = e.get("TTS_BASIC_AUTH", "").strip()
        bearer = e.get("TTS_API_KEY", "").strip()
        if basic and bearer:
            raise TtsError(
                "TTS_BASIC_AUTH dan TTS_API_KEY sama-sama memakai header Authorization; pakai salah satu "
                "(atau header lain lewat TTS_EXTRA_HEADERS)"
            )
        if basic:
            if ":" not in basic:
                raise TtsError("TTS_BASIC_AUTH harus berformat user:password")
            headers["Authorization"] = "Basic " + base64.b64encode(basic.encode()).decode()
        elif bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        for part in e.get("TTS_EXTRA_HEADERS", "").split(";"):
            if part.strip():
                name, sep, value = part.partition(":")
                if not sep or not name.strip():
                    raise TtsError("TTS_EXTRA_HEADERS harus berformat 'Nama: nilai; Nama2: nilai2'")
                headers[name.strip()] = value.strip()
        try:
            timeout = int(e.get("TTS_TIMEOUT", "120") or "120")
        except ValueError:
            raise TtsError("TTS_TIMEOUT harus bilangan bulat") from None
        return cls(
            base_url=base,
            model=e.get("TTS_MODEL", "tts-1").strip() or "tts-1",
            voice=e.get("TTS_VOICE", "default").strip() or "default",
            response_format=e.get("TTS_FORMAT", "wav").strip() or "wav",
            language=(e.get("TTS_LANGUAGE", "").strip() or None),
            timeout=timeout,
            headers=headers,
        )

    @property
    def host(self) -> str:
        return urlparse(self.base_url).hostname or "?"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):  # noqa: D401 - menolak semua redirect
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _request(cfg: TtsConfig, method: str, path: str, body: dict | None = None, timeout: int | None = None) -> tuple[int, bytes, str]:
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(cfg.headers)
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(cfg.base_url + path, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=timeout or cfg.timeout) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise TtsError(f"respons terlalu besar (> {MAX_RESPONSE_BYTES // (1024 * 1024)} MB)")
            return resp.status, raw, resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            raise TtsError("server mengarahkan ulang (redirect); ditolak demi keamanan kredensial") from None
        snippet = exc.read(300).decode("utf-8", "replace").replace("\n", " ")
        if exc.code in (401, 403):
            raise TtsError(f"HTTP {exc.code}: kredensial ditolak (periksa TTS_BASIC_AUTH / TTS_API_KEY)") from None
        raise TtsError(f"HTTP {exc.code}: {snippet}") from None
    except urllib.error.URLError as exc:
        raise TtsError(f"tidak bisa menghubungi {cfg.host}: {getattr(exc, 'reason', exc)}") from None
    except TimeoutError:
        raise TtsError(f"timeout menghubungi {cfg.host}") from None


def _is_audio(raw: bytes) -> bool:
    return raw.startswith(AUDIO_MAGIC) or raw[4:8] == b"ftyp"  # ftyp = MP4/M4A


def synthesize(cfg: TtsConfig, text: str) -> bytes:
    text = " ".join(text.split())
    if not text:
        raise TtsError("teks narasi kosong")
    if len(text) > MAX_TEXT_CHARS:
        raise TtsError(f"narasi terlalu panjang ({len(text)} > {MAX_TEXT_CHARS} karakter)")
    body: dict = {"model": cfg.model, "voice": cfg.voice, "input": text, "response_format": cfg.response_format}
    if cfg.language:
        body["language"] = cfg.language
    _, raw, ctype = _request(cfg, "POST", "/v1/audio/speech", body)
    if "json" in ctype.lower() or raw[:1] in (b"{", b"["):
        raise TtsError("server membalas JSON, bukan audio: " + raw[:200].decode("utf-8", "replace"))
    if not _is_audio(raw):
        raise TtsError("respons bukan audio yang dikenali")
    return raw


def list_voices(cfg: TtsConfig, timeout: int = 15) -> list[dict] | None:
    """Daftar suara dari GET /v1/audio/voices, atau None bila server tidak menyediakannya."""
    try:
        _, raw, _ = _request(cfg, "GET", "/v1/audio/voices", timeout=timeout)
        data = json.loads(raw)
    except (TtsError, ValueError):
        return None
    items = data.get("voices", data.get("data")) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return None
    out: list[dict] = []
    for v in items:
        if isinstance(v, str):
            out.append({"id": v, "name": v, "type": ""})
        elif isinstance(v, dict):
            vid = v.get("voice_id") or v.get("id") or v.get("name")
            if vid:
                out.append({"id": str(vid), "name": str(v.get("name") or vid), "type": str(v.get("type") or "")})
    return out or None


def resolve_voice(cfg: TtsConfig) -> TtsConfig:
    """Pastikan TTS_VOICE ada di server. VoiceStudio TIDAK menolak nama suara yang salah: ia diam-diam memakai suara
    bawaan, sehingga user mengira memakai suara klonnya. Nama lengkap yang unik diubah menjadi id-nya."""
    voices = list_voices(cfg)
    if voices is None:  # server tanpa daftar suara: percaya konfigurasi
        return cfg
    want = cfg.voice.strip().lower()
    if any(v["id"].lower() == want for v in voices):
        return cfg
    named = [v for v in voices if v["name"].lower() == want]
    if len(named) == 1:
        return dataclasses.replace(cfg, voice=named[0]["id"])
    avail = ", ".join(f"{v['name']} (id {v['id']})" for v in voices if v["type"] != "openai_alias")
    raise TtsError(
        f"suara '{cfg.voice}' tidak ada di server (server akan DIAM-DIAM memakai suara bawaan). "
        f"Isi TTS_VOICE dengan id suara. Tersedia: {avail[:500] or 'hanya suara bawaan'}"
    )


def health(cfg: TtsConfig, timeout: int = 6) -> tuple[bool, str]:
    try:
        status, _, _ = _request(cfg, "GET", "/health", timeout=timeout)
        return True, f"HTTP {status}"
    except TtsError as exc:
        return False, str(exc)


def audio_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise TtsError("tidak bisa membaca durasi audio hasil TTS") from None


def probe(cfg: TtsConfig, out=print) -> int:
    """Diagnosis untuk menemukan cara memakai suara: tidak mencetak kredensial."""
    out(f"host   : {cfg.host}  (model={cfg.model!r} voice={cfg.voice!r} format={cfg.response_format})")
    ok, detail = health(cfg)
    out(f"/health: {'OK' if ok else 'GAGAL'}  {detail}")
    if not ok:
        return 1
    for path in ("/engines", "/models"):
        try:
            _, raw, _ = _request(cfg, "GET", path, timeout=15)
            out(f"{path}: {raw[:500].decode('utf-8', 'replace')}")
        except TtsError as exc:
            out(f"{path}: {exc}")
    try:
        _, raw, _ = _request(cfg, "GET", "/openapi.json", timeout=20)
        paths = sorted(json.loads(raw).get("paths", {}))
        interesting = [p for p in paths if any(k in p.lower() for k in ("voice", "profile", "clone", "speech", "tts", "audio"))]
        out(f"path API terkait suara ({len(interesting)} dari {len(paths)}):")
        for p in interesting[:60]:
            out(f"   {p}")
    except (TtsError, ValueError) as exc:
        out(f"/openapi.json: {exc}")
    try:
        resolved = resolve_voice(cfg)
        out(f"suara  : OK ('{cfg.voice}' -> id {resolved.voice})" if resolved.voice != cfg.voice else f"suara  : OK ('{cfg.voice}' ada di server)")
    except TtsError as exc:
        out(f"suara  : PERINGATAN: {exc}")
        return 1
    try:
        data = synthesize(cfg, "Halo, ini tes suara dari Clautele.")
        with tempfile.NamedTemporaryFile(suffix=".wav") as f:
            f.write(data)
            f.flush()
            dur = audio_duration(Path(f.name))
        out(f"sintesis: OK, {len(data)} byte, durasi {dur:.1f} detik")
        return 0
    except TtsError as exc:
        out(f"sintesis: GAGAL: {exc}")
        return 1


def main(argv: list[str]) -> int:
    from .config import load_dotenv

    load_dotenv(Path(".env"))
    try:
        cfg = TtsConfig.from_env()
    except TtsError as exc:
        print(f"Konfigurasi TTS salah: {exc}", file=sys.stderr)
        return 2
    if cfg is None:
        print("TTS_BASE_URL belum diisi.", file=sys.stderr)
        return 2
    if argv and argv[0] == "--probe":
        return probe(cfg)
    if len(argv) == 2:
        try:
            Path(argv[1]).write_bytes(synthesize(cfg, argv[0]))
        except TtsError as exc:
            print(f"GAGAL: {exc}", file=sys.stderr)
            return 1
        print(f"OK {argv[1]}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
