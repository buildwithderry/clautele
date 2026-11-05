# Claude Code CLI mode headless (`-p`): izin, format output, dan resume

**Ringkasan eksekutif (Layer 4)**
- `claude -p` menjalankan satu giliran tanpa terminal; `--output-format stream-json` memberi event realtime.
- Tanpa TTY, permintaan izin tidak bisa dijawab: `--permission-prompts none` menolak otomatis, sehingga bot harus menawarkan izin lewat mekanisme lain.
- Percakapan dilanjutkan dengan `--resume <session-id>`.

## Kutipan
> -p, --print Print response and exit (useful for pipes). Note: **The workspace trust dialog is skipped when Claude is run in non-interactive mode** (via -p, or when stdout is not a TTY, e.g. piped or redirected output). **==Only use this in directories you trust.==**

> --output-format <format> Output format (only works with --print): "text" (default), "json" (single result), or **=="stream-json" (realtime streaming)==**

> --permission-prompts <target> Who answers permission prompts with --print: "host" (the SDK host or --permission-prompt-tool) or "none" (**==nobody: anything that would prompt is denied automatically==**; the permission mode still decides everything else)

> -r, --resume [value] **==Resume a conversation by session ID or name==**, or open interactive picker with optional search term

> --dangerously-skip-permissions **Bypass all permission checks.** Recommended only for sandboxes with no internet access.

---
Sumber: output `claude --help`, Claude Code 2.1.318, dijalankan di VPS pada 2026-11-05 (dibaca penuh, 313 baris)
Untuk: proyek clautele-telegram-bridge (keputusan desain runner dan model izin). Usulan lokasi PARA: 3 Resources (referensi CLI yang dipakai proyek)
Catatan Claude (bukan isi sumber): pada probe lokal dengan model haiku, tool `AskUserQuestion` tidak ditemukan di mode `-p`, sehingga Claude bertanya lewat teks biasa. Itu sebabnya clautele memakai penanda `<<ASK>>` buatan sendiri (lihat `keputusan-desain.md`). Ini pengamatan satu kali, belum tentu berlaku di versi atau model lain.
