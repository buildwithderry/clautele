# Checklist proyek

## Selesai
- [x] Runner subprocess + parser stream-json, batal & timeout
- [x] Perintah `/start_claude`, `/end_claude`, `/new`, `/stop`, `/status`, `/mode`, `/model`, `/id`
- [x] Progres realtime di Telegram
- [x] Pertanyaan → tombol, jawaban bebas
- [x] Tombol izinkan tool yang ditolak
- [x] Docker multi-stage, compose, `.env.example`
- [x] 36 test otomatis (config, parser, runner, store, alur bot dengan Telegram & claude palsu)
- [x] Smoke test: Claude Code di container berhasil autentikasi dengan kredensial yang di-mount

## Belum
- [ ] Uji langsung dengan token bot Telegram asli (butuh token dari pemilik)
- [ ] Pesan suara / foto / dokumen sebagai input
- [ ] Server MCP `ask_user` untuk pertanyaan sinkron
- [ ] Persetujuan izin per perintah (bukan per nama tool)

## Hemingway Bridge (untuk sesi berikutnya)
Mulai dari: isi `.env` (token + user ID), `docker compose up -d --build`, kirim `/start_claude` lalu uji pertanyaan
dan tombol izin. Jika tombol pertanyaan tidak muncul, cek apakah Claude menaruh `<<ASK>>` (lihat
`keputusan-desain.md` poin 2).
