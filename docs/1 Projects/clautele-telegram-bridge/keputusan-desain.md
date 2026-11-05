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
