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
