"""Entry point: python -m clautele"""

from __future__ import annotations

import logging
import shutil
import sys

from telegram.error import InvalidToken, NetworkError
from telegram.ext import Application

from .bot import ClauteleBot
from pathlib import Path

from .config import Config, ConfigError, load_dotenv
from .store import StateStore


def main() -> int:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    # Token ada di URL request httpx; jangan cetak di log INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Mode host (tanpa Docker): muat .env dari folder kerja. Variabel yang sudah ada tidak ditimpa.
    load_dotenv(Path(".env"))

    try:
        cfg = Config.from_env()
    except ConfigError as exc:
        print(f"Konfigurasi salah: {exc}", file=sys.stderr)
        return 2

    if shutil.which(cfg.claude_bin) is None:
        print(
            f"Peringatan: '{cfg.claude_bin}' tidak ada di PATH. Bot tetap jalan, "
            "tapi prompt akan gagal sampai Claude Code terpasang.",
            file=sys.stderr,
        )

    cfg.workdir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    bot = ClauteleBot(cfg, StateStore(cfg.data_dir / "state.json"))
    app = (
        Application.builder()
        .token(cfg.telegram_token)
        .concurrent_updates(True)  # agar /stop bisa masuk saat Claude bekerja
        .post_init(ClauteleBot.post_init)
        .build()
    )
    bot.register(app)
    logging.getLogger("clautele").info(
        "Clautele jalan. workdir=%s user_diizinkan=%d mode=%s",
        cfg.workdir,
        len(cfg.allowed_user_ids),
        cfg.permission_mode,
    )
    try:
        app.run_polling(drop_pending_updates=True)
    except InvalidToken:
        # Pesan bawaan library memuat token mentah; jangan sampai masuk log.
        print("TELEGRAM_BOT_TOKEN ditolak oleh Telegram. Periksa nilainya di .env.", file=sys.stderr)
        return 3
    except NetworkError as exc:
        print(f"Tidak bisa menghubungi Telegram: {type(exc).__name__}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
