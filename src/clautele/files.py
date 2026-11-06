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
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}  # yang bisa diputar langsung di Telegram
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


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def video_system_prompt(outbox: Path, inbox: Path, max_mb: int, has_maker: bool = False, has_tts: bool = False) -> str:
    """Panduan video untuk Claude; hanya diberikan bila ffmpeg benar-benar terpasang."""
    target = max(1, max_mb - 5)
    rule = (
        "ATURAN VIDEO (wajib): jika user meminta video, animasi, reel, story, atau konten video apa pun, "
        "hasilnya HARUS file MP4 yang kamu buat sendiri lalu kirim lewat penanda <<FILE>>. DILARANG menjawab "
        "dengan HTML, CSS, JavaScript, skrip, atau instruksi merekam layar/memakai aplikasi lain. "
        "Jika Bash ditolak karena izin, tetap pakai Bash (user menyetujui lewat tombol); jangan beralih ke format lain. "
    )
    maker = (
        "Untuk video bergaya slide/teks neon (konten Instagram, penjelasan poin demi poin, promo, ajakan komentar): "
        f"tulis spec JSON dengan tool Write (JANGAN heredoc/cat lewat Bash), lalu jalankan `clautele-video spec.json {outbox}/nama.mp4` "
        "dengan Bash timeout 600000 (render bisa beberapa menit). Jalankan clautele-video SENDIRIAN sebagai satu perintah Bash: "
        "jangan digabung dengan &&, ;, atau | (perintah berantai ditolak seluruhnya bila salah satu bagiannya belum diizinkan). "
        "Periksa hasil dengan perintah TERPISAH, mis. `ffprobe -v error -show_entries format=duration -of compact hasil.mp4` "
        "(ffprobe diizinkan otomatis). "
        'Spec: {"size":"story|square|portrait|landscape|WxH","fps":30,"footer":"@akun","audio":"musik.mp3 (opsional)",'
        '"scenes":[{"label":"01","title":"JUDUL","body":"isi singkat","color":"cyan|magenta|green|yellow|orange|red|blue|purple|white|#RRGGBB","duration":4}]}. '
        "Maks 40 scene dan 180 detik. Pecah materi jadi scene pendek: judul <= 6 kata, isi <= 2 kalimat, 3-5 detik. "
        "ILUSTRASI (wajib untuk video penjelasan, jangan hanya teks): beri tiap scene yang membahas sesuatu yang bisa "
        'digambar field "draw" berisi 3-8 elemen animasi yang menggambarkan KONTEKSNYA, mis. membahas denah/blueprint -> '
        '{"t":"floorplan"}; data -> icon database; server/cloud/aplikasi/orang -> icon server|cloud|app|person; alur -> '
        'arrow dengan "dots":true; lapisan/domain -> box bersusun + arrow; perbandingan sebelum/sesudah -> {"t":"chaos"}; '
        'angka/tren -> bars; ajakan follow/like -> box + icon heart "loop":"rise". Jadwalkan kemunculan lewat "at" (detik) '
        'agar gambar tumbuh bertahap, dan beri "loop":"pulse|float|spin" pada elemen kunci. Elemen: icon, box, rect, circle, '
        "line, arrow, poly, text, bars, floorplan, chaos; koordinat x,y 0-100 (pusat elemen) di panggung di bawah judul. "
        "Skema lengkap + daftar ikon: `clautele-video --help`. Pada scene bergambar isi (body) cukup satu kalimat pendek. "
        "Render scene bergambar sekitar 5x durasi video, jadi jaga total video <= 90 detik. "
        "Gunakan story (9:16) untuk Instagram Reels/Story, portrait untuk feed. Jalankan `clautele-video --help` bila ragu. "
        "Isi footer HANYA dengan akun/teks yang disebut user; jangan mengarang nama akun (bisa milik orang lain). "
        "Perintah ini mengizinkan dirinya sendiri; rendernya memakan waktu sekitar 3-4x durasi video, jadi jangan membuat video lebih panjang dari yang diminta. "
        "WAJIB pakai clautele-video untuk setiap video baru berbasis teks/slide/animasi teks, TERMASUK saat user menulis "
        "\"pakai ffmpeg\" atau \"dengan ffmpeg\": clautele-video sudah memakai ffmpeg di dalamnya, dan itu jalur yang tidak "
        "butuh izin. Panggil ffmpeg langsung hanya untuk mengedit video/gambar milik user (potong, gabung, kompres, ambil "
        "frame) atau efek yang jelas tidak bisa dibuat clautele-video. "
        if has_maker
        else ""
    )
    voice = (
        'SUARA/NARASI: spec mendukung "narration":"teks yang dibacakan" per scene (maks 500 karakter) memakai suara '
        "milik user lewat TTS. Pakai hanya bila user meminta suara, narasi, atau voice over. Tulis seperti diucapkan "
        "(angka dieja, singkatan dijelaskan, kalimat pendek), 1-3 kalimat per scene. Durasi scene otomatis menyesuaikan "
        "panjang suara. Jika TTS gagal (mis. komputer user mati), sampaikan apa adanya dan tawarkan video tanpa suara; "
        "jangan berpura-pura sudah ada suara. "
        if has_maker and has_tts
        else ""
    )
    return (
        rule
        + maker
        + voice
        + "ffmpeg dan ffprobe tersedia lewat Bash. "
        f"MEMBUAT/MENGEDIT video untuk user: simpan hasil di {outbox} sebagai MP4 agar bisa diputar langsung di "
        "Telegram: `-c:v libx264 -pix_fmt yuv420p -c:a aac -movflags +faststart` (tanpa audio: `-an`). "
        f"Ukuran akhir harus di bawah {target} MB; jika lebih, turunkan resolusi (`-vf scale=-2:720`) atau naikkan "
        "`-crf` (24-30). Server hanya punya 2 CPU: pakai `-preset veryfast`, dan batasi durasi/resolusi untuk "
        "pekerjaan besar. Umum: potong `-ss MULAI -to AKHIR -i in.mp4`, gabung dengan concat demuxer, "
        "kecilkan `-vf scale`, ambil audio `-vn`, GIF, slideshow dari gambar (`-loop 1 -t DETIK -i gambar.png`), "
        "teks di video `drawtext` dengan fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf. "
        f"MELIHAT video dari user (di {inbox}): kamu tidak bisa menonton atau mendengarnya. Cek metadata dengan "
        "`ffprobe -v error -show_format -show_streams`, lalu ambil beberapa frame "
        "(`ffmpeg -i in.mp4 -vf fps=1/5 -frames:v 12 frame_%02d.jpg`) dan baca gambarnya dengan Read; "
        "jelaskan ke user bahwa kamu hanya melihat cuplikan gambar, bukan suaranya. "
        "Simpan hasil sementara di folder kerja, jangan menimpa file asli user, dan beri nama hasil yang jelas."
    )


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
