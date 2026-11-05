"""Penyimpanan state per chat (session id Claude, mode, model) dalam satu file JSON."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ChatState:
    session_id: str | None = None
    permission_mode: str | None = None  # None = pakai default config
    model: str | None = None  # None = pakai default config
    total_cost_usd: float = 0.0
    turns: int = 0
    active: bool = False  # sesi Claude aktif? diatur lewat /start_claude dan /end_claude
    granted_tools: list = field(default_factory=list)  # tool yang diizinkan user lewat tombol
    last_prompt: str | None = None  # untuk "Izinkan & ulangi"
    prompt_hash: str | None = None  # sidik jari instruksi sistem saat sesi dibuat (lihat bot._compose_prompt)


class StateStore:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, ChatState] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return
        for key, val in raw.items():
            known = {k: v for k, v in val.items() if k in ChatState.__dataclass_fields__}
            self._data[key] = ChatState(**known)

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({k: asdict(v) for k, v in self._data.items()}, indent=2)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".state-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self._path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def get(self, chat_id: int) -> ChatState:
        with self._lock:
            return self._data.setdefault(str(chat_id), ChatState())

    def save(self) -> None:
        with self._lock:
            self._flush()

    def reset_session(self, chat_id: int) -> None:
        with self._lock:
            state = self._data.setdefault(str(chat_id), ChatState())
            state.session_id = None
            state.last_prompt = None
            state.turns = 0
            state.total_cost_usd = 0.0
            self._flush()
