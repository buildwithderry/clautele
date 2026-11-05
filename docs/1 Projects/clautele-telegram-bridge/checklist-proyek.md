# Checklist proyek

## Selesai
- [x] Runner subprocess + parser stream-json, batal & timeout
- [x] Perintah `/start_claude`, `/end_claude`, `/new`, `/stop`, `/status`, `/mode`, `/model`, `/id`
- [x] Progres realtime di Telegram
- [x] Pertanyaan → tombol, jawaban bebas
- [x] Tombol izinkan tool yang ditolak
- [x] Docker multi-stage, compose, `.env.example`
- [x] Mode host: `deploy/install-host.sh` + template service (ditulis, **belum dipasang**, lihat bawah)
- [x] Sesi otomatis direset saat instruksi berubah; ffprobe diizinkan; aturan 'pakai ffmpeg' (v0.5.1)
- [x] `clautele-video` renderer neon + aturan video=MP4 (v0.5.0)
- [x] Video: kirim streaming, buat/edit dengan ffmpeg, izin per perintah (v0.4.0)
- [x] Kirim/terima file, foto, dokumen (v0.3.0)
- [x] 2FA TOTP (`/login`, `/logout`), wajib di mode host
- [x] 150 test otomatis (RFC 6238, kabur lewat symlink/path traversal, izin granular, video nyata dengan teks 'bermusuhan')
- [x] Smoke test: Claude Code di container berhasil autentikasi dengan kredensial yang di-mount

## Belum
- [ ] **Validasi TTS terhadap VoiceStudio asli**: isi `TTS_BASIC_AUTH` di `.env`, jalankan `--probe`, uji suara kloning 'adult', lalu beri tag versi
- [ ] Pengetatan tunnel: password acak + allowlist path (`/health`, `/v1/audio/speech`, `/v1/audio/transcriptions`)
- [ ] Transkripsi pesan suara lewat `/v1/audio/transcriptions` (menggantikan rencana Whisper di VPS)
- [ ] Pasang service host: ditolak pengaman Claude Code ("Unauthorized Persistence"); pemilik harus menjalankan sendiri: (1) `python -m clautele.totp` di terminal pribadi, isi `TOTP_SECRET` di `.env`; (2) `docker compose stop clautele && bash deploy/install-host.sh`
- [ ] Push ke GitHub (VPS belum punya kredensial GitHub)
- [ ] Uji langsung dengan token bot Telegram asli (butuh token dari pemilik)
- [ ] v0.6.0: transkripsi suara + subtitle otomatis (faster-whisper, opsional lewat build arg)
- [ ] Bot API server lokal agar batas unduh 20 MB naik (video besar dari user)
- [ ] Izin sinkron lewat `--permission-prompt-tool` (MCP) agar tidak perlu menyuruh Claude mengulang
- [ ] Gaya video selain neon (tema di spec)
- [ ] Varian image dengan Remotion (jika dibutuhkan; periksa lisensi)
- [ ] Server MCP `ask_user` untuk pertanyaan sinkron

## Hemingway Bridge (untuk sesi berikutnya)
Mulai dari: isi `.env` (token + user ID), `docker compose up -d --build`, kirim `/start_claude` lalu uji pertanyaan
dan tombol izin. Jika tombol pertanyaan tidak muncul, cek apakah Claude menaruh `<<ASK>>` (lihat
`keputusan-desain.md` poin 2).
