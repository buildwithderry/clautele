"""Pengiriman file ke user dan penerimaan file dari user.

Keluar: Claude menaruh penanda di akhir balasan (boleh lebih dari satu):

    <<FILE>>{"path": "outbox/laporan.pdf", "caption": "Laporan"}<<END>>

Karena mengirim file dari server ke Telegram adalah jalur kebocoran data jika Claude terkena
prompt injection, setiap path divalidasi ketat: harus di dalam SEND_ROOTS (setelah symlink
diselesaikan), tidak cocok daftar tolak (kunci, kredensial, .env), dan tidak melebihi batas ukuran.
"""

from __future__ import annotations

import fnmatch
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

FILE_RE = re.compile(r"<<FILE>>(.*?)<<END>>", re.DOTALL)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PHOTO_MAX_BYTES = 10 * 1024 * 1024  # batas Telegram untuk send_photo
MAX_FILES_PER_REPLY = 5

# Nama berkas yang tidak pernah dikirim (cocok pada nama saja, huruf kecil).
DENY_NAME_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.kdbx",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    ".credentials.json",
    "credentials*",
    "*.credentials",
    ".netrc",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
    "secrets.*",
    "*.secret",
    "state.json",
)
# Pengecualian: berkas contoh yang memang aman dibagikan.
ALLOW_SUFFIXES = (".example", ".sample", ".template")
# Folder yang tidak pernah dikirim isinya.
DENY_DIR_NAMES = {".ssh", ".aws", ".gnupg", ".kube", ".docker", ".claude", "claude-config", ".git"}


class SendError(Exception):
    """Alasan file tidak boleh/bisa dikirim (aman ditampilkan ke user)."""


@dataclass(frozen=True)
class FileRef:
    path: str
    caption: str = ""


def extract_files(text: str) -> tuple[str, list[FileRef]]:
    """Kembalikan (teks tanpa penanda, daftar FileRef). Penanda rusak dibuang diam-diam."""
    refs: list[FileRef] = []
    for m in FILE_RE.finditer(text):
        raw = m.group(1).strip()
        path, caption = "", ""
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                path = str(data.get("path", "")).strip()
                caption = str(data.get("caption", "")).strip()
            elif isinstance(data, str):
                path = data.strip()
        except json.JSONDecodeError:
            path = raw  # toleransi: path polos tanpa JSON
        if path:
            refs.append(FileRef(path, caption[:900]))
    return FILE_RE.sub("", text).strip(), refs


def _denied_name(name: str) -> bool:
    low = name.lower()
    if low.endswith(ALLOW_SUFFIXES):
        return False
    return any(fnmatch.fnmatch(low, pat) for pat in DENY_NAME_PATTERNS)


def resolve_sendable(
    path_str: str, *, workdir: Path, roots: tuple[Path, ...], max_bytes: int
) -> Path:
    """Validasi path dari Claude. Mengembalikan path nyata, atau raise SendError."""
    if not path_str or "\x00" in path_str:
        raise SendError("path kosong")
    raw = Path(path_str).expanduser()
    candidate = raw if raw.is_absolute() else workdir / raw
    try:
        real = candidate.resolve(strict=True)  # ikuti symlink; harus ada
    except (FileNotFoundError, RuntimeError, OSError):
        raise SendError("file tidak ditemukan") from None
    if not real.is_file():
        raise SendError("bukan file biasa")
    real_roots = [r.resolve() for r in roots]
    if not any(real.is_relative_to(r) for r in real_roots):
        raise SendError("di luar folder yang boleh dikirim (SEND_ROOTS)")
    if _denied_name(real.name) or _denied_name(candidate.name):
        raise SendError("jenis file ini diblokir (kemungkinan berisi rahasia)")
    if any(part in DENY_DIR_NAMES for part in real.parts):
        raise SendError("folder ini diblokir (kemungkinan berisi rahasia)")
    size = real.stat().st_size
    if size == 0:
        raise SendError("file kosong")
    if size > max_bytes:
        raise SendError(f"terlalu besar ({size // (1024 * 1024)} MB, batas {max_bytes // (1024 * 1024)} MB)")
    return real


def is_photo(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS and path.stat().st_size <= PHOTO_MAX_BYTES


def safe_filename(name: str | None, fallback: str = "file") -> str:
    base = Path(name or "").name  # buang komponen direktori
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE).strip("._")
    return (base or fallback)[:100]


def inbox_target(inbox_dir: Path, original_name: str | None, *, fallback: str, now: float | None = None) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() if now is None else now))
    inbox_dir.mkdir(parents=True, exist_ok=True)
    target = inbox_dir / f"{stamp}-{safe_filename(original_name, fallback)}"
    n = 1
    while target.exists():  # dua file di detik yang sama
        target = target.with_name(f"{target.stem}-{n}{target.suffix}")
        n += 1
    return target


def files_system_prompt(outbox: Path, inbox: Path, max_mb: int) -> str:
    return (
        "Kamu dikendalikan lewat Telegram. "
        f"File yang dikirim user disimpan di {inbox}; path-nya diberikan di pesan, dan kamu bisa "
        "membacanya (gambar dan PDF bisa dibaca dengan tool Read). "
        "Jika user meminta sebuah file (gambar, dokumen, ekspor, dll.) atau hasil kerjamu paling baik "
        f"berupa file, simpan di {outbox} lalu akhiri balasan dengan penanda (JSON satu baris, boleh beberapa): "
        '<<FILE>>{"path": "/path/lengkap/file.ext", "caption": "keterangan singkat"}<<END>> '
        f"Bot mengirimkannya ke user. Hanya file di dalam {outbox} yang bisa dikirim, jadi salin dulu ke sana "
        f"bila filenya ada di tempat lain. Batas {max_mb} MB per file; file rahasia (.env, kunci, kredensial) "
        "selalu ditolak. Jangan mengirim file yang tidak diminta user, dan jangan mengklaim sudah terkirim "
        "tanpa penanda."
    )
