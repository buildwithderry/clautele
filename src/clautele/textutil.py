"""Utilitas teks untuk Telegram (batas 4096 karakter per pesan)."""

from __future__ import annotations

from typing import Any

TELEGRAM_LIMIT = 4096
SAFE_CHUNK = 3900  # sisakan ruang untuk penanda "(1/3)"


def split_message(text: str, limit: int = SAFE_CHUNK) -> list[str]:
    """Pecah teks panjang; utamakan batas paragraf, lalu baris, lalu spasi."""
    text = text.strip()
    if not text:
        return ["(kosong)"]
    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if cut < limit // 2:  # tidak ada titik potong yang wajar
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    if len(chunks) > 1:
        total = len(chunks)
        chunks = [f"{c}\n\n({i}/{total})" for i, c in enumerate(chunks, 1)]
    return chunks


def _shorten(value: str, n: int = 80) -> str:
    value = " ".join(value.split())
    return value if len(value) <= n else value[: n - 1] + "…"


def describe_tool_use(name: str, tool_input: dict[str, Any] | None) -> str:
    """Satu baris ringkas tentang tool yang sedang dipakai Claude."""
    inp = tool_input or {}
    detail = ""
    for key in ("command", "file_path", "path", "pattern", "url", "query", "description"):
        if inp.get(key):
            detail = _shorten(str(inp[key]))
            break
    return f"🔧 {name}: {detail}" if detail else f"🔧 {name}"


def format_denials(denials: list[Any]) -> str:
    names: list[str] = []
    for d in denials:
        if isinstance(d, dict):
            names.append(str(d.get("tool_name") or d.get("tool") or "?"))
        else:
            names.append(str(d))
    uniq = sorted(set(names))
    if not uniq:
        return ""
    return (
        "⚠️ Ditolak karena butuh izin: "
        + ", ".join(uniq)
        + "\nUbah /mode atau tambahkan ke CLAUDE_ALLOWED_TOOLS di .env."
    )
