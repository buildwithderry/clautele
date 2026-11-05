# Arsitektur

```
Telegram ──(long polling)──▶ bot.py ──▶ runner.py ──spawn──▶ claude -p --output-format stream-json
   ▲                           │             │                    (cwd = /workspace, resume sesi)
   │  pesan progres/jawaban    │             └─ baca event JSON per baris (stdout)
   └───────────────────────────┘
                 store.py (state.json: session_id, mode, model, izin tambahan, active)
```

| Modul | Tugas |
|---|---|
| `config.py` | Baca & validasi `.env`; menolak start tanpa token/allowlist |
| `runner.py` | Susun argumen CLI, jalankan subprocess, urai `stream-json`, batalkan/timeout |
| `asks.py` | Penanda `<<ASK>>` → pertanyaan + opsi (fallback: daftar bernomor) |
| `bot.py` | Handler perintah, tombol, pesan progres, pengiriman hasil |
| `store.py` | State per chat dalam satu file JSON (tulis atomik) |
| `textutil.py` | Pecah pesan >4096 karakter, ringkas deskripsi tool |

## Format event stream-json yang dipakai (diamati di claude 2.1.318)
- `system/init` membawa `session_id`.
- `assistant` berisi blok `tool_use` (name, input) atau `text`.
- `user` berisi `tool_result`.
- `result` berisi `result`, `is_error`, `total_cost_usd`, `num_turns`, `permission_denials`.

## Docker
Image multi-stage: `base` (node 22 + python + Claude Code CLI) → `test` (menjalankan pytest) → `runtime`
(non-root, uid 1000). Volume: `/workspace` (kerja Claude), `/home/node/.claude` (kredensial + riwayat sesi),
`/data` (state bot).
