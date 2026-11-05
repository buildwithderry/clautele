"""Usulan izin granular dari penolakan izin Claude.

Terverifikasi dengan claude 2.1.318: aturan `Bash(ffmpeg *)` hanya mengizinkan perintah ffmpeg, dan perintah
berantai (`;`, `&&`, `|`) diperiksa per bagian, jadi `ffmpeg ...; ffprobe ...` butuh dua aturan.
Karena itu tombol izin mengusulkan aturan per-executable, bukan seluruh Bash.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Any

MAX_OPTIONS = 6
# Substitusi perintah, subshell, redirect proses, atau banyak baris: terlalu sulit dinilai dengan aman.
_UNSAFE_RE = re.compile(r"\$\(|`|<\(|>\(|\n|\r")
_SPLIT_RE = re.compile(r"\s*(?:;|&&|\|\||\|)\s*")
_EXE_RE = re.compile(r"[A-Za-z0-9._/+-]+")
# Izin untuk executable ini setara menjalankan kode bebas, jadi ditandai berbahaya.
POWERFUL = {
    "bash", "sh", "zsh", "dash", "fish", "python", "python3", "node", "deno", "bun", "perl", "ruby", "php",
    "sudo", "su", "doas", "env", "xargs", "eval", "exec", "ssh", "scp", "docker", "kubectl", "nsenter", "find",
    "awk", "sed", "tee", "dd", "rm", "chmod", "chown", "curl", "wget", "nc", "ncat", "git",
}


@dataclass(frozen=True)
class GrantOption:
    rules: tuple[str, ...]
    label: str
    broad: bool = False


def _exe_of(segment: str) -> str | None:
    try:
        parts = shlex.split(segment)
    except ValueError:
        return None
    if not parts:
        return None
    exe = parts[0]
    if "=" in exe or not _EXE_RE.fullmatch(exe):  # VAR=nilai di depan, atau karakter aneh
        return None
    return exe


def bash_rules(command: str) -> tuple[str, ...] | None:
    """Aturan Bash(exe *) untuk setiap bagian perintah, atau None jika tidak bisa dinilai aman."""
    command = (command or "").strip()
    if not command or _UNSAFE_RE.search(command):
        return None
    rules: list[str] = []
    for segment in _SPLIT_RE.split(command):
        if not segment.strip():
            return None
        exe = _exe_of(segment)
        if exe is None:
            return None
        rule = f"Bash({exe} *)"
        if rule not in rules:
            rules.append(rule)
    return tuple(rules)


def options_for(denials: list[Any]) -> list[GrantOption]:
    out: list[GrantOption] = []
    seen: set[tuple[str, ...]] = set()

    def add(opt: GrantOption) -> None:
        if opt.rules not in seen and len(out) < MAX_OPTIONS:
            seen.add(opt.rules)
            out.append(opt)

    bash_denied = False
    for d in denials:
        if not isinstance(d, dict) or not d.get("tool_name"):
            continue
        name = str(d["tool_name"])
        if name != "Bash":
            add(GrantOption((name,), f"✅ Izinkan {name}"))
            continue
        bash_denied = True
        rules = bash_rules(str((d.get("tool_input") or {}).get("command", "")))
        if rules:
            exes = [r[len("Bash(") : -len(" *)")] for r in rules]
            powerful = [e for e in exes if e.rsplit("/", 1)[-1] in POWERFUL]
            names = ", ".join(exes)
            if powerful:
                add(GrantOption(rules, f"⚠️ Izinkan {names} (bisa menjalankan kode bebas)", broad=True))
            else:
                add(GrantOption(rules, f"✅ Izinkan perintah: {names}"))
    if bash_denied:
        add(GrantOption(("Bash",), "⚠️ Izinkan SEMUA perintah Bash", broad=True))
    return out
