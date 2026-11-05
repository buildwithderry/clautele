# Keputusan desain

## 1. Satu proses `claude -p` per pesan + `--resume`
Bukan proses interaktif yang hidup terus. Lebih sederhana, tahan crash, dan konteks tetap lewat `session_id`.
Konsekuensi: tiap giliran membayar start-up CLI. Alternatif (`--input-format stream-json`) dipertimbangkan, belum perlu.

## 2. Pertanyaan lewat penanda `<<ASK>>`, bukan AskUserQuestion
Probe lokal (claude 2.1.318, model haiku): `AskUserQuestion` tidak tersedia di mode `-p`; Claude bertanya dengan teks
biasa. Maka Claude diberi instruksi (via `--append-system-prompt`) untuk menutup balasan dengan
`<<ASK>>{"question": "...", "options": [...]}<<END>>`. Bot mengubahnya jadi tombol. Fallback: daftar bernomor di akhir
balasan yang didahului pertanyaan. Ketik bebas selalu bisa karena jawaban hanyalah prompt berikutnya.
**Risiko:** bergantung pada Claude mematuhi instruksi; kalau tidak, user tetap bisa mengetik balasan.
**Opsi lanjutan:** server MCP `ask_user` agar pertanyaan sinkron dan tidak bergantung pada kepatuhan prompt.

## 3. Izin: tolak otomatis + tombol izinkan
`--permission-prompts none` membuat apa pun yang butuh izin ditolak. Daftar penolakan dari event `result`
(`permission_denials`) ditampilkan sebagai tombol. Menekan "Izinkan" menyimpan tool di state chat dan menambahkannya
ke `--allowed-tools` pada giliran berikutnya. Izin berlaku per nama tool (mis. seluruh `Bash`), bukan per perintah, dan
dihapus oleh `/end_claude`.

## 4. Keamanan default
- Allowlist user ID wajib; bot menolak start tanpanya.
- `bypassPermissions` butuh konfirmasi `ALLOW_BYPASS_PERMISSIONS=true`.
- `TELEGRAM_BOT_TOKEN` dihapus dari environment proses Claude (yang bisa menjalankan Bash).
- Container non-root, `no-new-privileges`, tanpa port terbuka.
- Token tidak dicetak di log (httpx diredam, `InvalidToken` ditangkap; ditemukan bocor saat uji).

## 5. Auth Claude di Docker
Folder `claude-config/` di-mount ke `/home/node/.claude` dengan `CLAUDE_CONFIG_DIR`. Terverifikasi: hanya
`.credentials.json` yang perlu disalin dari host. Tanpa `CLAUDE_CONFIG_DIR`, Claude minta `~/.claude.json` yang
berada di luar folder dan hilang saat container dibuat ulang.

## 6. Tiga tingkat akses (sandbox → folder → host penuh)
Repo ini untuk dibagikan, jadi default harus aman: Docker dengan `/workspace` saja. Akses lebih luas adalah opt-in
(`WORKSPACE_DIR`, atau mode host lewat `deploy/install-host.sh`). Mount socket Docker sengaja **tidak** disediakan:
setara akses root ke host.
Pemicu keputusan: Claude di container tidak bisa menjalankan `docker ps` (tidak ada CLI/socket), padahal pemilik VPS
ingin mengelola server dari Telegram. Pemilik memilih tingkat 3 untuk VPS-nya sendiri.
Mode host: venv di repo, `.env` dimuat aplikasi (`load_dotenv`; nilai berspasi seperti
`CLAUDE_ALLOWED_TOOLS=Read Grep Glob` tidak aman di-`source` lewat bash), service `systemd --user`.
Catatan operasional: Docker dan host memakai satu token bot, jadi hanya satu yang boleh jalan.

## 7. 2FA TOTP di dalam bot
Pemicu: di tingkat 3 akun Telegram yang diambil alih = shell di server. Allowlist user ID saja tidak cukup, karena
ID melekat pada akun.
- TOTP RFC 6238 ditulis sendiri dengan stdlib (hmac/struct), tanpa dependensi baru. Diverifikasi terhadap vektor uji
  RFC (`287082`, `081804`, `279037`).
- Status login hanya di memori: restart = terkunci. Sesi absolut (bukan sliding) agar masa berlaku pasti.
- Anti replay (langkah waktu yang sama tak bisa dipakai dua kali), anti brute force (5 salah → kunci 15 menit),
  pembanding waktu-konstan, pesan `/login` dihapus.
- Wajib bila `CLAUTELE_SANDBOX` bukan `docker` (mode host); tidak ada opsi mematikannya. Di Docker opsional.
- **Batas yang jujur:** 2FA melindungi dari pemakai akun Telegram yang dicuri, bukan dari penyerang yang sudah punya
  akses ke server atau `.env` (secret ada di sana). Karena itu `.env` harus `chmod 600`.
- Jam server harus akurat (NTP); toleransi hanya ±30 detik.

## 8. File dari dan ke Telegram (v0.3.0)
Bug yang dilaporkan: Claude menjawab "file ada di sandbox, tidak bisa dikirim" dan tidak bisa membaca file user,
karena bot hanya meneruskan teks. Perbaikan:
- **Keluar:** penanda `<<FILE>>{json}<<END>>` (pola sama dengan `<<ASK>>`). Diverifikasi dengan Claude asli (haiku):
  file dibuat di `outbox/` dan penanda valid.
- **Masuk:** file diunduh ke `.clautele/inbox/<waktu>-<nama-aman>`, prompt memuat path absolut; Claude membaca dengan
  tool Read. Album digabung lewat debounce 1,5 detik per `media_group_id`.
- **Ancaman:** mengirim file ke Telegram = jalur eksfiltrasi bila Claude terkena prompt injection. Lapisan: (1) root
  default hanya `outbox/`, (2) `resolve()` mengikuti symlink sebelum cek root, (3) denylist nama (`.env`, kunci,
  kredensial) dan folder (`.ssh`, `.git`, …) pada path asli maupun yang diminta, (4) batas ukuran dan jumlah,
  (5) 2FA di depan semuanya, (6) `SEND_FILES=false` mematikan.
- **Batas jujur:** denylist tidak bisa mengenali rahasia di berkas bernama biasa. Penyerang yang sudah menguasai Claude
  masih bisa menyalin isi rahasia ke `outbox/` dengan nama lain. Mitigasinya ada di izin tool (Bash tidak diizinkan
  permanen) dan 2FA, bukan di filter ini.
- Suara/audio/video disimpan tetapi tidak ditranskripsi (belum ada tool untuk itu).

## 9. Video, izin per perintah (v0.4.0)
Kebutuhan: user minta video (kirim, buat, edit). Telegram menerima file apa pun sebagai dokumen, tetapi video harus dikirim
dengan `send_video(supports_streaming=True)` agar bisa diputar; MP4 H.264 + AAC paling aman, dengan fallback ke dokumen.
- **ffmpeg, bukan Remotion.** ffmpeg menutup kebutuhan: potong, gabung, kompres, teks, slideshow, GIF, ambil audio, dan
  "melihat" video lewat frame. Remotion (video dari kode React) butuh Chromium + Node di image, ratusan MB tambahan, dan
  memiliki lisensi khusus (setahu saya gratis untuk individu/tim kecil, berbayar untuk perusahaan lebih besar; cek
  remotion.dev/license). Tidak cocok jadi bawaan repo yang dibagikan. Opsi nanti: varian image terpisah.
- **Whisper ditunda ke v0.5.0.** Berguna untuk transkripsi pesan suara dan subtitle otomatis. Rencana: `faster-whisper`
  (CTranslate2, tanpa PyTorch) model `small`/`base` int8, opsional lewat build arg agar image default tidak membengkak.
  VPS pemilik: 2 CPU, 7,6 GB RAM, jadi `small` jalan tetapi lambat; model diunduh saat pertama dipakai.
- **Verifikasi izin dengan Claude asli (2.1.318):** `Bash(ffmpeg *)` hanya mengizinkan ffmpeg; perintah berantai
  (`;`, `&&`) diperiksa per bagian, jadi `echo x; ffmpeg ...` dengan aturan echo saja ditolak. Maka tombol izin
  mengusulkan satu aturan per executable dan menandai executable yang setara kode bebas (python, bash, curl, git, ...).
  Substitusi perintah `$(...)`, backtick, banyak baris, dan `VAR=x cmd` tidak diusulkan sebagai aturan sempit.
  Jebakan saat menguji: `date`, `sleep`, dan `python3 --version` otomatis diizinkan di mode acceptEdits, sehingga
  tes yang memakai perintah itu menghasilkan kesimpulan keliru. Pakai perintah yang pasti butuh izin (mis. `ffmpeg`).
- Uji end-to-end: Claude asli (sonnet) membuat MP4 H.264 1280x720 3 detik dari satu permintaan, hanya dengan izin
  ffmpeg/ffprobe, dan penanda `<<FILE>>` lolos validasi.
- **Biaya:** image 1,07 GB → 1,7 GB (ffmpeg Debian membawa banyak dependensi). Alternatif lebih kecil: binary ffmpeg statis
  (mengunduh dari luar, perlu verifikasi checksum), belum dipilih.
