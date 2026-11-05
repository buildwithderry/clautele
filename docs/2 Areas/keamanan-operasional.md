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
- [ ] Akun Telegram pemilik memakai verifikasi dua langkah (mengambil alih akun = shell di server)
- [ ] `journalctl --user -u clautele` tidak memuat token (diredam di `__main__.py`)

## Fakta yang perlu diingat
- Izin "Bash" yang diberikan lewat tombol berlaku untuk **semua** perintah Bash sampai `/end_claude`.
- Claude di container hanya melihat `/workspace`, tetapi punya akses jaringan keluar.
