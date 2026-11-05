"""Protokol tanya-jawab: Claude bertanya, user memilih tombol atau mengetik sendiri.

Mode `claude -p` tidak punya tool AskUserQuestion (terverifikasi di claude 2.1.318),
jadi Claude diminta menaruh penanda terstruktur di akhir balasan:

    <<ASK>>{"question": "Pilih DB?", "options": ["Postgres", "SQLite"]}<<END>>

Bot mengubahnya menjadi tombol. Jika penanda tidak ada, ada fallback heuristik
untuk daftar bernomor/berhuruf di akhir balasan.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

ASK_RE = re.compile(r"<<ASK>>(.*?)<<END>>", re.DOTALL)
OPTION_LINE_RE = re.compile(r"^\s*(?:\d{1,2}|[A-Ha-h])[.)]\s+(.+?)\s*$")
MAX_OPTIONS = 8
MAX_LABEL = 60

SYSTEM_PROMPT = (
    "Kamu dikendalikan lewat Telegram dan user tidak melihat terminal. "
    "Tool AskUserQuestion tidak tersedia. Jika kamu perlu keputusan dari user, "
    "akhiri balasanmu dengan SATU penanda persis seperti ini (JSON satu baris): "
    '<<ASK>>{"question": "pertanyaan singkat", "options": ["opsi 1", "opsi 2"]}<<END>> '
    "Maksimal 6 opsi, tiap opsi pendek. User bisa memilih opsi atau mengetik jawaban bebas. "
    "Setelah menaruh penanda, berhenti dan tunggu jawaban. Jangan memakai penanda untuk "
    "sekadar basa-basi. Jawab dalam bahasa yang dipakai user. "
    "Izin: bot berjalan tanpa terminal, jadi perintah yang butuh izin ditolak otomatis dan user bisa menyetujuinya "
    "lewat tombol. Penolakan hanya berlaku untuk perintah ITU, bukan seluruh sesi: jangan menyimpulkan bahwa Bash "
    "tidak bisa dipakai. Perintah lain mungkin sudah diizinkan, jadi tetap coba, dan jangan mengganti permintaan "
    "user dengan skrip yang harus dijalankan sendiri oleh user."
)


@dataclass(frozen=True)
class Question:
    question: str
    options: tuple[str, ...]


def _clean_options(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        text = " ".join(str(item).split())
        if text:
            out.append(text)
    return tuple(out[:MAX_OPTIONS])


def extract_question(text: str) -> tuple[str, Question | None]:
    """Kembalikan (teks tanpa penanda, Question atau None)."""
    matches = list(ASK_RE.finditer(text))
    if matches:
        last = matches[-1]
        cleaned = ASK_RE.sub("", text).strip()
        try:
            data = json.loads(last.group(1).strip())
            question = str(data.get("question", "")).strip()
            options = _clean_options(data.get("options"))
        except (json.JSONDecodeError, AttributeError):
            return cleaned, None
        if question or options:
            return cleaned, Question(question or "Pilih salah satu:", options)
        return cleaned, None

    # Fallback: blok daftar bernomor/berhuruf di ujung balasan.
    lines = text.rstrip().splitlines()
    opts: list[str] = []
    i = len(lines) - 1
    while i >= 0 and OPTION_LINE_RE.match(lines[i]):
        opts.append(OPTION_LINE_RE.match(lines[i]).group(1))  # type: ignore[union-attr]
        i -= 1
    opts.reverse()
    if 2 <= len(opts) <= MAX_OPTIONS:
        lead = "\n".join(lines[: i + 1]).strip()
        if lead.rstrip().endswith("?") or any(
            l.strip().endswith("?") for l in lines[max(0, i - 2) : i + 1]
        ):
            return text.strip(), Question("Pilih salah satu:", tuple(opts))
    return text.strip(), None


def button_label(option: str) -> str:
    return option if len(option) <= MAX_LABEL else option[: MAX_LABEL - 1] + "…"
