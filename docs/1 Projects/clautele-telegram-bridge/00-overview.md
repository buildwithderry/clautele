# Proyek: clautele-telegram-bridge

**Hasil akhir:** bot Telegram yang meneruskan chat ke Claude Code CLI di VPS, bisa dipakai siapa saja lewat
Docker + `.env`.

**Status:** v0.1.0, selesai dibangun dan diuji otomatis; belum diuji langsung dengan token Telegram asli.

## Kebutuhan dari pemilik
1. Bicara interaktif dengan Claude Code di VPS lewat bot Telegram.
2. Hasil CLI terlihat di Telegram (tool yang dipakai, jawaban akhir, biaya).
3. Kalau Claude bertanya: pilih tombol **atau** ketik jawaban sendiri.
4. Bisa memulai dan mengakhiri sesi Claude (`/start_claude`, `/end_claude`).
5. Konfigurasi lewat `.env`, ada `.env.example`, jalan di Docker.
6. Dokumentasi dikelola dengan PARA + distill.

## Fitur → perintah
| Kebutuhan | Implementasi |
|---|---|
| Mulai/akhiri sesi | `/start_claude`, `/end_claude`; pesan biasa ditolak sampai sesi aktif |
| Lihat proses CLI | Pesan progres yang diedit: `🔧 Bash: ls`; `SHOW_TOOL_OUTPUT=true` menambah cuplikan output |
| Pertanyaan Claude | Penanda `<<ASK>>` → tombol inline; ketik bebas tetap bisa |
| Izin ditolak | Tombol "Izinkan <tool>" lalu Claude melanjutkan |
| Batalkan | `/stop` membunuh seluruh grup proses |
| Konteks | `--resume <session_id>` per chat; `/new` untuk memulai ulang |

## Berkas terkait
- [arsitektur](arsitektur.md)
- [keputusan-desain](keputusan-desain.md)
- [checklist-proyek](checklist-proyek.md)
