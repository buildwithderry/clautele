# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id-ID/1.1.0/) dan
[Semantic Versioning](https://semver.org/lang/id/). Selama versi 0.x, perubahan yang tidak kompatibel
bisa terjadi di versi minor dan akan ditandai **BREAKING**.

## [Belum dirilis]

## [0.5.0] - 2026-11-06

### Ditambahkan
- **`clautele-video`**: renderer video slide bergaya neon (MP4 H.264) dari spec JSON, berbasis ffmpeg. Latar gelap +
  grid, teks berpendar (glow), bingkai neon, animasi masuk/keluar, footer, audio opsional, ukuran story/square/portrait/
  landscape atau `WxH`. Maks 40 scene dan 180 detik; teks tak muat diperkecil otomatis dan hanya dipotong (`…`) sebagai
  jalan terakhir. Dipakai Claude lewat satu perintah yang diizinkan otomatis (`Bash(clautele-video *)`), output hanya
  boleh di dalam folder kerja. Mode host: dipasang oleh `deploy/install-host.sh` ke `~/.local/bin`.

### Diperbaiki
- **Permintaan video dijawab dengan file HTML** ("buka di browser lalu rekam layar"). Penyebab: `Write` diizinkan
  otomatis sedangkan `Bash` (ffmpeg) butuh tombol izin, sehingga Claude memilih jalur tanpa izin. Sekarang instruksi
  sistem mewajibkan hasil MP4, melarang HTML/skrip/rekam layar, dan melarang berganti format bila Bash ditolak; alat
  `clautele-video` tidak memerlukan izin.
- Instruksi video menyuruh menulis spec dengan `Write` (bukan heredoc via Bash, yang memicu tombol izin yang tidak perlu).

### Catatan
- Render sekitar 3-4x durasi video di server 2 CPU (video 73 detik ≈ 4 menit).
- Whisper (transkripsi/subtitle) bergeser ke v0.6.0.

## [0.4.0] - 2026-11-06

### Ditambahkan
- **Video:** file `.mp4`/`.mov`/`.m4v` dikirim sebagai video yang bisa diputar langsung (streaming); jika Telegram
  menolak formatnya, otomatis dikirim sebagai dokumen. Foto juga punya fallback yang sama.
- **ffmpeg + ffprobe + font di image Docker** untuk membuat dan mengedit video (potong, gabung, kompres, teks,
  slideshow, GIF, ambil audio). Mati dengan `--build-arg WITH_FFMPEG=false`.
- Panduan video untuk Claude (format Telegram-friendly, batas ukuran, cara "melihat" video lewat frame) yang
  hanya diberikan bila `ffmpeg` terpasang.
- **Izin per perintah:** tombol penolakan izin kini mengusulkan `Bash(ffmpeg *)` (bukan seluruh Bash). Perintah
  berantai diusulkan per bagian (`ffmpeg ...; ffprobe ...` → dua aturan). Executable yang setara menjalankan
  kode bebas (python, bash, sudo, curl, git, ...) ditandai ⚠️.

### Berubah
- **BREAKING (kecil):** callback tombol izin memakai indeks (`grant:0`), bukan nama tool; tombol lama di chat yang
  sudah terkirim menjadi "kedaluwarsa". Tombol "Izinkan semua" dihapus.
- Image Docker membesar sekitar 0,6 GB (1,07 → 1,7 GB) karena ffmpeg.

### Catatan
- Claude tidak bisa menonton/mendengar video; ia hanya melihat frame yang diambil lewat ffmpeg. Transkripsi suara
  belum ada.
- Video dari user dibatasi 20 MB oleh Bot API Telegram.

## [0.3.0] - 2026-11-06

### Ditambahkan
- **Kirim file ke Telegram:** Claude menaruh penanda `<<FILE>>{"path","caption"}<<END>>`; gambar dikirim sebagai foto,
  lainnya sebagai dokumen (maks 5 per balasan, batas 50 MB).
- **Terima file dari Telegram:** foto, dokumen, suara, audio, dan video disimpan ke `.clautele/inbox/` lalu path-nya
  diteruskan ke Claude (keterangan jadi instruksi). Album foto digabung menjadi satu giliran. Batas 20 MB.
- Variabel `SEND_FILES`, `SEND_ROOTS`, `SEND_MAX_MB`, `UPLOAD_MAX_MB`.

### Keamanan
- Pengiriman file hanya dari `SEND_ROOTS` (default: `.clautele/outbox` saja), setelah symlink diselesaikan; blokir
  `.env`, kunci, kredensial, dan folder `.ssh`/`.aws`/`.claude`/`.git`; nama file masuk disanitasi.

### Diperbaiki
- Claude sebelumnya mengaku "file ada di sandbox dan tidak bisa dikirim" karena bot hanya meneruskan teks.

## [0.2.0] - 2026-11-06

### Ditambahkan
- 2FA TOTP (RFC 6238): `/login <kode>`, `/logout`, `python -m clautele.totp`. Anti replay, kunci setelah 5 kali salah,
  sesi kedaluwarsa (`TOTP_SESSION_MINUTES`).
- Mode host tanpa Docker: `deploy/install-host.sh` dan template service `systemd --user`.
- Pembaca `.env` bawaan (`load_dotenv`) agar nilai berspasi aman dan env yang sudah ada tidak ditimpa.
- Bagian "Pilih tingkat akses" di README (sandbox, folder tertentu, host penuh).

### Berubah
- **BREAKING (hanya mode host):** `TOTP_SECRET` wajib bila bot dijalankan di luar image Docker resmi
  (`CLAUTELE_SANDBOX=docker`). Pengguna Docker tidak terpengaruh.
- `/status` menampilkan status 2FA.

## [0.1.0] - 2026-11-05

### Ditambahkan
- Bot Telegram untuk Claude Code (`claude -p --output-format stream-json --resume`), long polling.
- Perintah `/start_claude`, `/end_claude`, `/new`, `/stop`, `/status`, `/mode`, `/model`, `/id`.
- Progres tool realtime; pertanyaan Claude menjadi tombol (penanda `<<ASK>>`) atau jawaban bebas.
- Tombol "Izinkan" untuk tool yang ditolak; allowlist `ALLOWED_USER_IDS` wajib.
- Docker multi-stage (test + runtime non-root), `docker-compose.yml`, `.env.example`.
- Dokumentasi PARA di `docs/`.

[Belum dirilis]: https://github.com/buildwithderry/clautele/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/buildwithderry/clautele/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/buildwithderry/clautele/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/buildwithderry/clautele/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/buildwithderry/clautele/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/buildwithderry/clautele/releases/tag/v0.1.0
