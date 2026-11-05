# Clautele

Ngobrol dengan **Claude Code** yang berjalan di VPS Anda lewat **bot Telegram**. Jalan di Docker, dikonfigurasi lewat `.env`.

- Lihat proses CLI langsung di Telegram (tool yang dipakai, jawaban, biaya)
- Claude bertanya → pilih tombol **atau** ketik jawaban sendiri
- Mulai/akhiri sesi kapan saja (`/start_claude`, `/end_claude`)
- Tool yang ditolak bisa diizinkan dengan satu tombol
- Aman secara default: hanya user ID yang Anda daftarkan

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

## Pilih tingkat akses

Seberapa banyak yang boleh disentuh Claude ditentukan oleh cara Anda menjalankan bot.

| Tingkat | Cara | Claude bisa |
|---|---|---|
| 1. Sandbox (default) | `docker compose up -d` | Hanya isi `workspace/` |
| 2. Folder tertentu | Docker + `WORKSPACE_DIR=/path/folder` di `.env` | Hanya folder itu |
| 3. Penuh di host | `bash deploy/install-host.sh` (tanpa Docker) | Semua yang bisa dilakukan akun Linux Anda, termasuk `docker`, `git`, dan semua folder |

**Tingkat 3 bukan sandbox.** Siapa pun yang lolos `ALLOWED_USER_IDS` (atau yang mengambil alih akun Telegram Anda)
praktis punya shell di server. Pakai hanya di server milik sendiri, biarkan `CLAUDE_PERMISSION_MODE=acceptEdits`
dan jangan aktifkan `ALLOW_BYPASS_PERMISSIONS`. Mode host memakai login Claude yang sudah ada di akun itu
(`~/.claude`), jadi `claude-config/` tidak dipakai.

Skrip host memasang *systemd user service* (tanpa `sudo`), membaca `.env` dari folder repo, dan menolak jalan kalau
container Docker `clautele` masih aktif (dua instance dengan token sama bentrok). Perintah berguna:
`systemctl --user status clautele`, `journalctl --user -u clautele -f`, `systemctl --user disable --now clautele`.

## Izin & keamanan

Bot berjalan tanpa terminal, jadi permintaan izin Claude **ditolak otomatis** lalu ditawarkan sebagai tombol
"Izinkan". Izin berlaku per nama tool (mis. semua `Bash`) sampai `/end_claude`. Untuk mengizinkan tool tertentu secara
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

## Dokumentasi

Dikelola dengan PARA, lihat [docs/README.md](docs/README.md): arsitektur, keputusan desain, dan catatan referensi
Claude Code CLI ada di sana.

## Cara kerja singkat

Tiap pesan menjalankan `claude -p --output-format stream-json --resume <session_id>` di `/workspace`. Event JSON dibaca
baris per baris untuk progres dan hasil akhir. Karena `AskUserQuestion` tidak tersedia di mode `-p`, Claude diinstruksikan
memakai penanda `<<ASK>>{...}<<END>>` yang diubah bot menjadi tombol.
