# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id-ID/1.1.0/) dan
[Semantic Versioning](https://semver.org/lang/id/). Selama versi 0.x, perubahan yang tidak kompatibel
bisa terjadi di versi minor dan akan ditandai **BREAKING**.

## [Belum dirilis]

## [0.6.0] - 2026-11-06

> Divalidasi terhadap VoiceStudio asli (lewat ngrok) dengan suara klon, Claude asli, dan kode bot: video neon 29 detik
> bernarasi terkirim sebagai video (audio AAC -22 dB rata-rata).

### Ditambahkan
- **Narasi suara (TTS)** lewat endpoint kompatibel OpenAI (`POST /v1/audio/speech`), mis. VoiceStudio di komputer
  lain. Klien stdlib `clautele.tts`: HTTPS wajib (kecuali loopback), redirect ditolak agar kredensial tidak ikut ke
  host lain, respons dibatasi ukuran dan harus benar-benar audio, kredensial tidak masuk ke pesan error atau
  `repr`. Variabel `TTS_BASE_URL`, `TTS_BASIC_AUTH` / `TTS_API_KEY`, `TTS_EXTRA_HEADERS`, `TTS_VOICE`, `TTS_MODEL`,
  `TTS_FORMAT`, `TTS_LANGUAGE`, `TTS_TIMEOUT`.
- `python -m clautele.tts --probe`: diagnosis (health, engine, path API terkait suara, uji sintesis) tanpa
  mencetak kredensial.
- Kolom `narration` per scene di `clautele-video`: semua narasi disintesis lebih dulu (gagal cepat sebelum render),
  durasi scene menyesuaikan panjang suara, scene tanpa narasi mendapat audio hening agar segmen seragam.
- `/status` menampilkan apakah TTS terjangkau dan apakah suara yang dipilih ada di server.
- **Validasi suara:** VoiceStudio tidak menolak nama suara yang salah, ia diam-diam memakai suara bawaan (terverifikasi:
  nama ngawur tetap "OK"). Klien memeriksa `TTS_VOICE` ke `GET /v1/audio/voices` dan menolak dengan daftar suara yang
  tersedia; nama lengkap yang unik diubah menjadi id-nya. Dipakai oleh `clautele-video`, `--probe`, dan `/status`.

### Diperbaiki
- Claude mengarang footer video (mis. akun yang bisa milik orang lain); kini footer hanya dari yang disebut user.
- Musik latar yang lebih pendek dari video **memotong video**; kini diulang (`-stream_loop`). Dengan narasi, musik
  dikecilkan di bawah suara.
- Pembaca `.env` bawaan memakai nilai pertama untuk kunci duplikat, sedangkan docker compose memakai yang terakhir;
  kini sama (yang terakhir menang).

### Catatan keamanan
- `CLAUDE_ALLOWED_TOOLS=*` **tidak** membuka semua izin (diuji: `ffmpeg` tetap ditolak); gunakan pola seperti
  `Bash(ffmpeg *)`.
- Kredensial TTS ada di environment container dan karena itu dapat dibaca proses yang dijalankan Claude.
- Menyalin `~/.claude/.credentials.json` dari host ke `claude-config/` memakai **refresh token yang sama** di dua tempat.
  Begitu salah satu memperbarui token, yang lain gagal dengan "OAuth session expired and could not be refreshed" dan bot
  berhenti menjawab. Login terpisah di dalam container (`docker compose exec -it clautele claude`, lalu `/login`)
  atau `ANTHROPIC_API_KEY` menghindarinya.

## [0.5.1] - 2026-11-06

### Diperbaiki
- **Fitur baru tidak berlaku pada percakapan yang sudah berjalan.** `claude --resume` memakai instruksi sistem dari
  giliran *pertama* sesi dan mengabaikan `--append-system-prompt` yang baru (terverifikasi dengan eksperimen bersih).
  Akibatnya sesi lama tidak pernah melihat aturan video, penanda file, dll., dan permintaan video tetap dijawab dengan
  HTML atau skrip `.sh`. Kini bot menyimpan sidik jari instruksi per chat; bila berubah (update bot, `.env`, ffmpeg
  baru terpasang), bot **memulai percakapan baru otomatis dan memberi tahu user**. Sesi dari versi lama (tanpa
  sidik jari) juga direset sekali.
- Perintah berantai `clautele-video ... && ffprobe ...` ditolak seluruhnya karena `ffprobe` belum diizinkan (izin
  diperiksa per bagian). `ffprobe` (baca metadata saja) kini diizinkan otomatis bersama `clautele-video`, dan instruksi
  menyuruh menjalankannya sebagai perintah terpisah.
- Permintaan "pakai ffmpeg" membuat Claude memanggil ffmpeg mentah (butuh tombol izin) dan melewati `clautele-video`.
  Instruksi kini menegaskan `clautele-video` wajib untuk video baru berbasis teks/slide, termasuk saat user menyebut
  ffmpeg.
- Penolakan izin untuk satu perintah dianggap Claude berlaku untuk seluruh sesi ("Bash tidak bisa dipakai"). Instruksi
  kini menyatakan penolakan hanya berlaku untuk perintah itu.

### Catatan
- Mengubah instruksi sistem berarti percakapan aktif dimulai ulang (konteks lama tidak dibawa). Itu disengaja dan
  selalu disertai pemberitahuan.

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

[Belum dirilis]: https://github.com/buildwithderry/clautele/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/buildwithderry/clautele/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/buildwithderry/clautele/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/buildwithderry/clautele/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/buildwithderry/clautele/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/buildwithderry/clautele/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/buildwithderry/clautele/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/buildwithderry/clautele/releases/tag/v0.1.0
