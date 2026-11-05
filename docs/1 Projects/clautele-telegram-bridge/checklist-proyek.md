# Checklist proyek

## Selesai
- [x] Runner subprocess + parser stream-json, batal & timeout
- [x] Perintah `/start_claude`, `/end_claude`, `/new`, `/stop`, `/status`, `/mode`, `/model`, `/id`
- [x] Progres realtime di Telegram
- [x] Pertanyaan → tombol, jawaban bebas
- [x] Tombol izinkan tool yang ditolak
- [x] Docker multi-stage, compose, `.env.example`
- [x] Mode host: `deploy/install-host.sh` + template service (ditulis, **belum dipasang**, lihat bawah)
- [x] 2FA TOTP (`/login`, `/logout`), wajib di mode host
- [x] 47 test otomatis (termasuk vektor RFC 6238) (config, parser, runner, store, alur bot dengan Telegram & claude palsu)
- [x] Smoke test: Claude Code di container berhasil autentikasi dengan kredensial yang di-mount

## Belum
- [ ] Pasang service host: ditolak pengaman Claude Code ("Unauthorized Persistence"); pemilik harus menjalankan sendiri: (1) `python -m clautele.totp` di terminal pribadi, isi `TOTP_SECRET` di `.env`; (2) `docker compose stop clautele && bash deploy/install-host.sh`
- [ ] Push ke GitHub (VPS belum punya kredensial GitHub)
- [ ] Uji langsung dengan token bot Telegram asli (butuh token dari pemilik)
- [ ] Pesan suara / foto / dokumen sebagai input
- [ ] Server MCP `ask_user` untuk pertanyaan sinkron
- [ ] Persetujuan izin per perintah (bukan per nama tool)

## Hemingway Bridge (untuk sesi berikutnya)
Mulai dari: isi `.env` (token + user ID), `docker compose up -d --build`, kirim `/start_claude` lalu uji pertanyaan
dan tombol izin. Jika tombol pertanyaan tidak muncul, cek apakah Claude menaruh `<<ASK>>` (lihat
`keputusan-desain.md` poin 2).
