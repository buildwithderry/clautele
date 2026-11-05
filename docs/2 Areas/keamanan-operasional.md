# Area: Keamanan operasional bot

**Standar yang dijaga:** bot hanya bisa dikendalikan pemiliknya, dan Claude tidak punya akses lebih dari yang disengaja.

## Checklist rutin (review bulanan)
- [ ] `ALLOWED_USER_IDS` hanya berisi orang yang memang boleh
- [ ] Tidak ada `ALLOW_BYPASS_PERMISSIONS=true` tanpa alasan
- [ ] `WORKSPACE_DIR` tidak menunjuk ke home atau folder berisi secret
- [ ] Token bot tidak pernah masuk git, log, atau chat (kalau bocor: `/revoke` di @BotFather)
- [ ] `docker compose build --no-cache` agar Claude Code dan dependensi terbarui
- [ ] `claude-config/` berisi kredensial: izin folder 700, jangan di-backup ke tempat publik
- [ ] `SHOW_TOOL_OUTPUT` mati kecuali perlu (output tool bisa memuat data sensitif)

## Mode host (tingkat 3)
- [ ] Hanya satu instance per token: hentikan container Docker sebelum service host (`getUpdates` 409 kalau bentrok)
- [ ] `CLAUDE_PERMISSION_MODE=acceptEdits`; jangan `bypassPermissions`
- [ ] `TOTP_SECRET` terisi, `.env` chmod 600, jam server sinkron (NTP)
- [ ] Verifikasi dua langkah bawaan Telegram aktif (Settings → Privacy and Security)
- [ ] Secret TOTP tidak pernah ditempel ke chat; jika terlanjur, buat baru dengan `python -m clautele.totp`
- [ ] `journalctl --user -u clautele` tidak memuat token (diredam di `__main__.py`)

## Izin
- [ ] Tinjau `/status` → "Izin tambahan"; `/end_claude` menghapusnya
- [ ] Jangan menaruh executable berbahaya (python, bash, curl) di `CLAUDE_ALLOWED_TOOLS` permanen

## File keluar
- [ ] `SEND_ROOTS` kosong atau sempit; jangan menunjuk ke folder berisi file konfigurasi proyek lain
- [ ] `ls <workdir>/.clautele/outbox` sesekali: bersihkan file lama
- [ ] `SEND_FILES=false` bila bot dipakai di lingkungan yang tidak mengizinkan data keluar

## Fakta yang perlu diingat
- Tombol izin mengusulkan aturan per perintah (`Bash(ffmpeg *)`). Hanya pilihan bertanda ⚠️ "SEMUA Bash" yang membuka seluruh Bash sampai `/end_claude`.
- Aturan sempit untuk `python`, `bash`, `curl`, `git`, `sudo`, dll. praktis setara akses penuh; label ⚠️ mengingatkan hal itu.
- Claude di container hanya melihat `/workspace`, tetapi punya akses jaringan keluar.
