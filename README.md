# Clautele

Ngobrol dengan **Claude Code** yang berjalan di VPS Anda lewat **bot Telegram**. Jalan di Docker, dikonfigurasi lewat `.env`.

- Lihat proses CLI langsung di Telegram (tool yang dipakai, jawaban, biaya)
- Claude bertanya → pilih tombol **atau** ketik jawaban sendiri
- Kirim foto/dokumen ke Claude, dan Claude bisa mengirim file hasil kerjanya ke chat
- Buat dan edit video (ffmpeg), hasilnya terkirim sebagai video yang bisa langsung diputar
- Mulai/akhiri sesi kapan saja (`/start_claude`, `/end_claude`)
- Tool yang ditolak bisa diizinkan dengan satu tombol
- Aman secara default: hanya user ID yang Anda daftarkan, plus **2FA TOTP** (Google Authenticator, Aegis, Authy, dll.)

> ⚠️ Bot ini memberi akses ke Claude Code, yang dapat membaca/menulis file dan menjalankan perintah di folder kerjanya.
> Isi `ALLOWED_USER_IDS` dengan benar dan arahkan `WORKSPACE_DIR` ke folder khusus, bukan home Anda.

## Mulai cepat

1. **Buat bot**: chat [@BotFather](https://t.me/BotFather) → `/newbot` → salin token. Cari user ID Anda lewat [@userinfobot](https://t.me/userinfobot).
2. **Siapkan konfigurasi**
   ```bash
   cp .env.example .env
   mkdir -p workspace claude-config
   # edit .env: TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, dan autentikasi Claude
   ```
3. **Autentikasi Claude** (pilih satu):
   - isi `ANTHROPIC_API_KEY` di `.env`, **atau**
   - pakai akun Claude: `cp ~/.claude/.credentials.json claude-config/` (setelah login `claude` di host), atau
     `docker compose run --rm clautele claude` lalu `/login`.
4. **Jalankan**
   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```
5. Di Telegram: `/start_claude`, lalu kirim pesan apa saja.

## Perintah

| Perintah | Fungsi |
|---|---|
| `/start_claude` | Mulai sesi (melanjutkan percakapan sebelumnya bila ada) |
| `/end_claude` | Akhiri sesi, hapus konteks dan izin tambahan |
| `/new` | Percakapan baru, sesi tetap aktif |
| `/stop` | Batalkan proses yang sedang berjalan |
| `/status` | Sesi, mode, model, biaya |
| `/mode` | Ganti permission mode lewat tombol |
| `/model <nama>` | Ganti model (kosong = default) |
| `/id` | Tampilkan user ID Anda |

## File dari dan ke Telegram

- **Kirim ke Claude:** kirim foto atau dokumen (keterangan = instruksi, mis. "ringkas PDF ini"). File disimpan di
  `<folder kerja>/.clautele/inbox/`; Claude bisa membaca gambar dan PDF. Suara/audio/video tersimpan, tetapi Claude
  tidak otomatis bisa mendengar/menontonnya. Album foto diproses sebagai satu pesan. Maks 20 MB (batas Telegram).
- **Terima dari Claude:** minta saja ("buatkan logo lalu kirim ke saya"). Claude menaruh file di
  `<folder kerja>/.clautele/outbox/` dan bot mengirimkannya. Maks 50 MB, 5 file per balasan.
- **Keamanan:** hanya `outbox/` yang boleh dikirim (lebarkan lewat `SEND_ROOTS`); `.env`, kunci, kredensial, dan
  folder `.ssh`/`.aws`/`.claude`/`.git` selalu diblokir. Daftar blokir tidak bisa mengenali rahasia di berkas
  bernama biasa (mis. `docker-compose.yml` berisi password), jadi jangan melebarkan `SEND_ROOTS` ke folder seperti itu.
  Matikan semuanya dengan `SEND_FILES=false`.

## Video

Image Docker menyertakan `ffmpeg` dan `ffprobe`. Contoh permintaan: *"buat video 5 detik latar biru dengan tulisan Halo"*,
atau kirim video dengan keterangan *"potong menit 0:10–0:25 lalu kecilkan jadi 720p"*.

- **Video bergaya neon/slide** (konten Instagram, penjelasan poin demi poin, promo): minta saja, mis. *"buatkan video
  Instagram gaya neon tentang apa itu EA, lalu ajak komen MAU"*. Claude menulis spec JSON dan memakai perintah
  `clautele-video` (renderer bawaan, diizinkan otomatis, tanpa tombol izin). Format 9:16 untuk Reels/Story, atau
  square/portrait/landscape. Cek sendiri: `docker compose exec clautele clautele-video --example`.
- Waktu render sekitar 3-4x durasi video di server 2 CPU (video 1 menit ≈ 3-4 menit).
- Hasil dikirim sebagai MP4 yang bisa diputar langsung (maks 50 MB; Claude diminta menjaga di bawah ±45 MB).
- Video dari Anda maksimal 20 MB (batas Bot API Telegram). Claude **tidak bisa menonton atau mendengar** video: ia
  mengambil beberapa frame lewat ffmpeg dan membacanya sebagai gambar.
- Server kecil (2 CPU) akan lambat untuk video panjang/resolusi tinggi; ada batas waktu `CLAUDE_TIMEOUT_SECONDS`.
- Tombol izin mengusulkan `Bash(ffmpeg *)`, jadi Anda tidak perlu memberi izin ke seluruh Bash.
- Image jadi sekitar 0,6 GB lebih besar. Tanpa video: `docker compose build --build-arg WITH_FFMPEG=false`.
- Mode host: pasang sendiri (`sudo apt install ffmpeg fonts-dejavu-core`); panduan video baru aktif jika `ffmpeg` ada di PATH.

## Percakapan dimulai ulang saat bot diperbarui

Instruksi untuk Claude hanya dibaca pada giliran pertama sebuah sesi. Karena itu, setelah update bot atau perubahan
`.env`, bot memulai percakapan baru secara otomatis dan memberi tahu Anda ("🔄 Instruksi bot sudah diperbarui…").
Konteks lama tidak dibawa; riwayatnya tetap ada di `claude-config/`.

## Pilih tingkat akses

Seberapa banyak yang boleh disentuh Claude ditentukan oleh cara Anda menjalankan bot.

| Tingkat | Cara | Claude bisa |
|---|---|---|
| 1. Sandbox (default) | `docker compose up -d` | Hanya isi `workspace/` |
| 2. Folder tertentu | Docker + `WORKSPACE_DIR=/path/folder` di `.env` | Hanya folder itu |
| 3. Penuh di host | `bash deploy/install-host.sh` (tanpa Docker) | Semua yang bisa dilakukan akun Linux Anda, termasuk `docker`, `git`, dan semua folder |

**Tingkat 3 bukan sandbox, dan 2FA TOTP wajib** (bot menolak start tanpa `TOTP_SECRET`). Siapa pun yang lolos `ALLOWED_USER_IDS` (atau yang mengambil alih akun Telegram Anda)
praktis punya shell di server. Pakai hanya di server milik sendiri, biarkan `CLAUDE_PERMISSION_MODE=acceptEdits`
dan jangan aktifkan `ALLOW_BYPASS_PERMISSIONS`. Mode host memakai login Claude yang sudah ada di akun itu
(`~/.claude`), jadi `claude-config/` tidak dipakai.

Skrip host memasang *systemd user service* (tanpa `sudo`), membaca `.env` dari folder repo, dan menolak jalan kalau
container Docker `clautele` masih aktif (dua instance dengan token sama bentrok). Perintah berguna:
`systemctl --user status clautele`, `journalctl --user -u clautele -f`, `systemctl --user disable --now clautele`.

## 2FA (TOTP)

Bot terkunci sampai Anda kirim `/login 123456` (kode 6 digit dari aplikasi authenticator). Sesi terbuka selama
`TOTP_SESSION_MINUTES` (default 60), lalu terkunci lagi; `/logout` mengunci seketika, restart bot juga mengunci.
Kode yang sudah dipakai ditolak, 5 kali salah mengunci 15 menit, dan pesan `/login` dihapus dari chat.

Setup (di terminal pribadi, jangan di chat):
```bash
python -m clautele.totp                      # cetak TOTP_SECRET baru + URI otpauth
# tambahkan TOTP_SECRET=... ke .env, masukkan kuncinya ke aplikasi authenticator, lalu uji:
python -m clautele.totp --verify 123456
```
Di Docker: `docker compose run --rm clautele python -m clautele.totp`. Wajib di mode host, opsional di Docker.

Ini melengkapi, bukan menggantikan, verifikasi dua langkah bawaan Telegram (Settings → Privacy and Security →
Two-Step Verification), yang melindungi akun Telegram Anda dari pengambilalihan. Aktifkan keduanya.

## Izin & keamanan

Bot berjalan tanpa terminal, jadi permintaan izin Claude **ditolak otomatis** lalu ditawarkan sebagai tombol
"Izinkan". Untuk Bash, tombol mengusulkan izin **per perintah** (mis. `Bash(ffmpeg *)`); pilihan "SEMUA Bash" selalu
terakhir dan bertanda ⚠️. Izin berlaku sampai `/end_claude`. Untuk mengizinkan tool tertentu secara
permanen, isi `CLAUDE_ALLOWED_TOOLS`, misalnya `Read Grep Glob "Bash(git status*)"`.

`bypassPermissions` mematikan semua pengecekan; hanya aktif jika `ALLOW_BYPASS_PERMISSIONS=true`. Token bot tidak
diteruskan ke proses Claude. Lihat [docs/2 Areas/keamanan-operasional.md](<docs/2 Areas/keamanan-operasional.md>).

## Konfigurasi

Semua variabel dijelaskan di [`.env.example`](.env.example).

## Pengembangan

```bash
docker build --target test .     # menjalankan seluruh test di dalam Docker
```

Tanpa Docker: `pip install -r requirements-dev.txt && pytest` (butuh Python 3.11+).

## Versi

Memakai [Semantic Versioning](https://semver.org/lang/id/); riwayat perubahan di [CHANGELOG.md](CHANGELOG.md).
Versi berjalan tampil di `/status`. Untuk memakai versi tertentu: `git checkout v0.2.0`.

## Dokumentasi

Dikelola dengan PARA, lihat [docs/README.md](docs/README.md): arsitektur, keputusan desain, dan catatan referensi
Claude Code CLI ada di sana.

## Cara kerja singkat

Tiap pesan menjalankan `claude -p --output-format stream-json --resume <session_id>` di `/workspace`. Event JSON dibaca
baris per baris untuk progres dan hasil akhir. Karena `AskUserQuestion` tidak tersedia di mode `-p`, Claude diinstruksikan
memakai penanda `<<ASK>>{...}<<END>>` yang diubah bot menjadi tombol.
