# Changelog

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id-ID/1.1.0/) dan
[Semantic Versioning](https://semver.org/lang/id/). Selama versi 0.x, perubahan yang tidak kompatibel
bisa terjadi di versi minor dan akan ditandai **BREAKING**.

## [Belum dirilis]

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

[Belum dirilis]: https://github.com/buildwithderry/clautele/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/buildwithderry/clautele/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/buildwithderry/clautele/releases/tag/v0.1.0
