"""Handler Telegram: menghubungkan chat ke sesi Claude Code."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import __version__
from .asks import SYSTEM_PROMPT, Question, button_label, extract_question
from .config import VALID_MODES, Config
from .grants import options_for
from .files import (
    MAX_FILES_PER_REPLY,
    FileRef,
    SendError,
    extract_files,
    files_system_prompt,
    inbox_target,
    is_photo,
    is_video,
    video_system_prompt,
    resolve_sendable,
)
from .runner import ClaudeRun, RunResult, assistant_blocks, build_args
from .store import StateStore
from .totp import TotpGate
from .textutil import describe_tool_use, format_denials, split_message

log = logging.getLogger("clautele")

PROGRESS_LINES = 12
EDIT_INTERVAL = 1.5  # detik; batas aman agar tidak kena flood limit Telegram

HELP = (
    "🤖 *Clautele*: ngobrol dengan Claude Code di server lewat Telegram\n\n"
    "/start\\_claude: mulai sesi Claude\n"
    "/end\\_claude: akhiri sesi (konteks dihapus)\n"
    "/new: mulai percakapan baru, sesi tetap aktif\n"
    "/stop: batalkan proses yang sedang berjalan\n"
    "/status: info sesi, mode, model, biaya\n"
    "/mode: ganti permission mode\n"
    "/model `<nama>`: ganti model (kosong = default)\n"
    "/id: tampilkan Telegram user ID Anda\n"
    "/login `<kode>`: buka kunci dengan kode 2FA (jika 2FA aktif)\n"
    "/logout: kunci kembali\n\n"
    "Anda juga bisa mengirim *foto atau dokumen* (dengan keterangan sebagai instruksi), dan Claude "
    "bisa mengirim file hasil kerjanya ke chat ini.\n\n"
    "Setelah /start\\_claude, kirim pesan biasa sebagai prompt. Kalau Claude bertanya, "
    "pilih tombol *atau* ketik jawaban sendiri."
)


class ClauteleBot:
    def __init__(self, cfg: Config, store: StateStore):
        self.cfg = cfg
        self.store = store
        self.runs: dict[int, ClaudeRun] = {}
        self.gate = TotpGate(cfg.totp_secret, session_seconds=cfg.totp_session_minutes * 60)

    # ---------- util ----------

    def _listed(self, update: Update) -> bool:
        user = update.effective_user
        return bool(user and user.id in self.cfg.allowed_user_ids)

    def _allowed(self, update: Update) -> bool:
        """Terdaftar di allowlist DAN (jika 2FA aktif) sesi sedang terbuka."""
        return self._listed(update) and self.gate.is_unlocked(update.effective_user.id)

    async def _deny(self, update: Update) -> None:
        user = update.effective_user
        uid = user.id if user else "?"
        if self._listed(update):
            if update.effective_message:
                await update.effective_message.reply_text(
                    "🔒 Terkunci. Kirim /login <kode 6 digit dari aplikasi authenticator>."
                )
            return
        log.warning("Akses ditolak untuk user id %s", uid)
        if update.effective_message:
            await update.effective_message.reply_text(
                f"⛔ Anda tidak diizinkan memakai bot ini. User ID Anda: {uid}"
            )

    async def cmd_login(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._listed(update):
            return await self._deny(update)
        msg = update.effective_message
        uid = update.effective_user.id
        if not self.gate.required:
            return await msg.reply_text("2FA tidak aktif (TOTP_SECRET kosong). Tidak perlu login.")
        ok, info = self.gate.attempt(uid, " ".join(ctx.args))
        # Hapus pesan berisi kode agar tidak tersisa di riwayat chat.
        try:
            await msg.delete()
        except TelegramError:
            pass
        log.info("Login 2FA %s untuk user id %s", "berhasil" if ok else "gagal", uid)
        await ctx.bot.send_message(update.effective_chat.id, ("🔓 " if ok else "❌ ") + info)

    async def cmd_logout(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._listed(update):
            return await self._deny(update)
        self.gate.lock(update.effective_user.id)
        await update.effective_message.reply_text("🔒 Terkunci. /login <kode> untuk membuka lagi.")

    # ---------- perintah ----------

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        await update.effective_message.reply_markdown(HELP)

    async def cmd_id(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        # Sengaja tanpa cek izin: dipakai untuk mengisi ALLOWED_USER_IDS.
        user = update.effective_user
        await update.effective_message.reply_text(f"User ID Anda: {user.id if user else '?'}")

    async def cmd_start_claude(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        chat_id = update.effective_chat.id
        state = self.store.get(chat_id)
        state.active = True
        self.store.save()
        resumed = "melanjutkan percakapan sebelumnya" if state.session_id else "percakapan baru"
        await update.effective_message.reply_text(
            f"✅ Sesi Claude aktif ({resumed}).\n"
            f"Folder kerja: {self.cfg.workdir}\n"
            f"Mode: {state.permission_mode or self.cfg.permission_mode}\n\n"
            "Kirim pesan apa saja sebagai prompt."
        )

    async def cmd_end_claude(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        chat_id = update.effective_chat.id
        run = self.runs.get(chat_id)
        if run:
            run.cancel()
        self.store.reset_session(chat_id)
        state = self.store.get(chat_id)
        state.active = False
        state.granted_tools = []
        self.store.save()
        await update.effective_message.reply_text(
            "🛑 Sesi Claude diakhiri dan konteks dihapus. /start_claude untuk mulai lagi."
        )

    async def cmd_new(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        chat_id = update.effective_chat.id
        if run := self.runs.get(chat_id):
            run.cancel()
        self.store.reset_session(chat_id)
        await update.effective_message.reply_text("🆕 Percakapan baru dimulai.")

    async def cmd_stop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        run = self.runs.get(update.effective_chat.id)
        if run is None:
            return await update.effective_message.reply_text("Tidak ada proses yang berjalan.")
        run.cancel()
        await update.effective_message.reply_text("⏹ Membatalkan proses…")

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        chat_id = update.effective_chat.id
        s = self.store.get(chat_id)
        lines = [
            f"Clautele v{__version__}",
            f"Sesi: {'aktif' if s.active else 'tidak aktif'}"
            + (" (sedang bekerja)" if chat_id in self.runs else ""),
            f"Session ID: {s.session_id or '-'}",
            f"Mode: {s.permission_mode or self.cfg.permission_mode}",
            f"Model: {s.model or self.cfg.model or 'default'}",
            f"Giliran: {s.turns} | Biaya sesi: ${s.total_cost_usd:.4f}",
            f"Izin tambahan: {', '.join(s.granted_tools) or '-'}",
            f"Folder kerja: {self.cfg.workdir}",
            "2FA: "
            + (
                "tidak aktif"
                if not self.gate.required
                else time.strftime(
                    "terbuka sampai %H:%M", time.localtime(self.gate.unlocked_until(update.effective_user.id))
                )
            ),
        ]
        await update.effective_message.reply_text("\n".join(lines))

    async def cmd_mode(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        s = self.store.get(update.effective_chat.id)
        current = s.permission_mode or self.cfg.permission_mode
        modes = [m for m in VALID_MODES if m != "bypassPermissions" or self.cfg.allow_bypass]
        rows = [
            [InlineKeyboardButton(("● " if m == current else "") + m, callback_data=f"mode:{m}")]
            for m in modes
        ]
        await update.effective_message.reply_text(
            f"Permission mode saat ini: {current}\nPilih mode baru:",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    async def cmd_model(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        s = self.store.get(update.effective_chat.id)
        s.model = " ".join(ctx.args).strip() or None
        self.store.save()
        await update.effective_message.reply_text(f"Model: {s.model or 'default'}")

    # ---------- pesan & tombol ----------

    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        chat_id = update.effective_chat.id
        if not self.store.get(chat_id).active:
            return await update.effective_message.reply_text(
                "Sesi Claude belum aktif. Kirim /start_claude dulu."
            )
        text = (update.effective_message.text or "").strip()
        if text:
            await self.run_prompt(ctx, chat_id, text)

    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if q is None or q.data is None:
            return
        if not self._allowed(update):
            return await q.answer("Tidak diizinkan.", show_alert=True)
        chat_id = q.message.chat_id
        state = self.store.get(chat_id)
        kind, _, value = q.data.partition(":")

        if kind == "mode":
            if value not in VALID_MODES or (value == "bypassPermissions" and not self.cfg.allow_bypass):
                return await q.answer("Mode tidak valid.", show_alert=True)
            state.permission_mode = value
            self.store.save()
            await q.answer(f"Mode: {value}")
            await q.edit_message_text(f"Permission mode: {value}")

        elif kind == "ask":
            options: list[str] = ctx.chat_data.get("pending_options", [])
            try:
                choice = options[int(value)]
            except (ValueError, IndexError):
                return await q.answer("Pilihan kedaluwarsa, ketik jawabanmu.", show_alert=True)
            if not state.active:
                return await q.answer("Sesi tidak aktif. /start_claude", show_alert=True)
            if chat_id in self.runs:
                return await q.answer("Claude masih bekerja. /stop untuk membatalkan.", show_alert=True)
            await q.answer()
            ctx.chat_data.pop("pending_options", None)
            await q.edit_message_reply_markup(reply_markup=None)
            await ctx.bot.send_message(chat_id, f"➡️ {choice}")
            await self.run_prompt(ctx, chat_id, choice)

        elif kind == "grant":
            pending: list[list[str]] = ctx.chat_data.get("pending_grants", [])
            try:
                rules = pending[int(value)]
            except (ValueError, IndexError):
                return await q.answer("Permintaan kedaluwarsa.", show_alert=True)
            if chat_id in self.runs:
                return await q.answer("Claude masih bekerja.", show_alert=True)
            state.granted_tools = list(dict.fromkeys([*state.granted_tools, *rules]))
            self.store.save()
            ctx.chat_data.pop("pending_grants", None)
            await q.answer("Diizinkan")
            await q.edit_message_reply_markup(reply_markup=None)
            await ctx.bot.send_message(chat_id, f"✅ Diizinkan: {', '.join(rules)}")
            await self.run_prompt(
                ctx,
                chat_id,
                f"Izin untuk {', '.join(rules)} sudah diberikan. Silakan lanjutkan tugas tadi.",
            )

        elif kind == "dismiss":
            await q.answer()
            await q.edit_message_reply_markup(reply_markup=None)

    # ---------- inti: menjalankan Claude ----------

    async def run_prompt(self, ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, prompt: str) -> None:
        if chat_id in self.runs:
            await ctx.bot.send_message(
                chat_id, "⏳ Claude masih bekerja. Tunggu selesai atau kirim /stop."
            )
            return
        state = self.store.get(chat_id)
        state.last_prompt = prompt
        # `--append-system-prompt` hanya berlaku pada giliran PERTAMA sesi; saat --resume, instruksi lama tetap
        # dipakai dan yang baru diabaikan (terverifikasi di claude 2.1.318). Maka sesi lama tidak akan pernah
        # melihat fitur/aturan baru. Bila instruksi berubah, mulai sesi baru dan beri tahu user.
        digest = hashlib.sha256(self._compose_prompt()[0].encode()).hexdigest()[:12]
        if state.session_id and state.prompt_hash != digest:
            log.info("Instruksi berubah (%s -> %s); memulai sesi baru", state.prompt_hash, digest)
            state.session_id = None
            state.turns = 0
            await ctx.bot.send_message(
                chat_id,
                "🔄 Instruksi bot sudah diperbarui sejak percakapan ini dimulai (mis. fitur video baru), jadi saya "
                "memulai percakapan baru agar semuanya berfungsi. Konteks lama tidak dibawa.",
            )
        state.prompt_hash = digest
        progress = _Progress(ctx.bot, chat_id, enabled=self.cfg.stream_progress)
        await progress.start()
        typing = asyncio.create_task(_typing_loop(ctx.bot, chat_id))
        started = time.monotonic()
        result = RunResult()
        try:
            result = await self._execute(chat_id, prompt, progress, allow_retry=True)
        except FileNotFoundError:
            result.text = (
                f"Perintah '{self.cfg.claude_bin}' tidak ditemukan. "
                "Pasang Claude Code atau atur CLAUDE_BIN."
            )
            result.is_error = True
        except Exception as exc:  # noqa: BLE001 - lapor ke user, jangan matikan bot
            log.exception("Gagal menjalankan Claude")
            result.text = f"Gagal menjalankan Claude: {exc}"
            result.is_error = True
        finally:
            typing.cancel()
            self.runs.pop(chat_id, None)

        elapsed = time.monotonic() - started
        if result.session_id:
            state.session_id = result.session_id
        if result.saw_result:
            state.turns += 1
            state.total_cost_usd += result.cost_usd
        self.store.save()

        if result.cancelled:
            await progress.finish("⏹ Dibatalkan.")
            return
        if result.timed_out:
            await progress.finish(f"⌛ Timeout setelah {self.cfg.timeout_seconds}s.")
            return

        footer = f"{'⚠️' if result.is_error else '✅'} {elapsed:.0f}s"
        if result.saw_result:
            footer += f" · {result.num_turns} langkah · ${result.cost_usd:.4f}"
        await progress.finish(footer)
        await self._deliver(ctx, chat_id, result)

    def _compose_prompt(self) -> tuple[str, list[str]]:
        """Instruksi sistem lengkap + izin bawaan. Dipakai untuk menjalankan Claude dan untuk sidik jari sesi."""
        cfg = self.cfg
        # clautele-video adalah alat bawaan kita (output dibatasi ke folder kerja), jadi diizinkan otomatis.
        has_maker = bool(shutil.which("ffmpeg") and shutil.which("clautele-video"))
        # ffprobe hanya membaca metadata; Claude memakainya untuk memeriksa hasil render. Tanpa izin ini, perintah
        # berantai seperti `clautele-video ... && ffprobe ...` ditolak seluruhnya (izin diperiksa per bagian).
        builtin_tools = (
            ["Bash(clautele-video *)", *(["Bash(ffprobe *)"] if shutil.which("ffprobe") else [])]
            if has_maker and cfg.send_files
            else []
        )
        parts = [cfg.append_system_prompt, SYSTEM_PROMPT]
        if cfg.send_files:
            parts.append(files_system_prompt(cfg.outbox_dir, cfg.inbox_dir, cfg.send_max_mb))
            if shutil.which("ffmpeg"):
                parts.append(
                    video_system_prompt(cfg.outbox_dir, cfg.inbox_dir, cfg.send_max_mb, has_maker=has_maker)
                )
        return "\n\n".join(p for p in parts if p), builtin_tools

    async def _execute(
        self, chat_id: int, prompt: str, progress: "_Progress", *, allow_retry: bool
    ) -> RunResult:
        state = self.store.get(chat_id)
        full_cfg_prompt, builtin_tools = self._compose_prompt()
        cfg = self.cfg
        cfg = replace(cfg, append_system_prompt=full_cfg_prompt)
        args = build_args(
            cfg,
            session_id=state.session_id,
            permission_mode=state.permission_mode,
            model=state.model,
            extra_allowed_tools=[*state.granted_tools, *builtin_tools],
        )
        run = ClaudeRun(cfg, args)
        self.runs[chat_id] = run

        async def on_event(event: dict[str, Any]) -> None:
            await self._on_event(event, progress)

        result = await run.run(prompt, on_event)
        resume_broken = (
            state.session_id
            and not result.saw_result
            and not result.cancelled
            and not result.timed_out
            and "conversation" in result.stderr_tail.lower()
        )
        if resume_broken and allow_retry:
            log.warning("Session %s tidak bisa dilanjutkan, mulai baru", state.session_id)
            state.session_id = None
            await progress.add("ℹ️ Sesi lama tidak ditemukan, memulai yang baru.")
            self.runs.pop(chat_id, None)
            return await self._execute(chat_id, prompt, progress, allow_retry=False)
        return result

    async def _on_event(self, event: dict[str, Any], progress: "_Progress") -> None:
        for block in assistant_blocks(event):
            if block.get("type") == "tool_use":
                await progress.add(describe_tool_use(block.get("name", "?"), block.get("input")))
        if self.cfg.show_tool_output and event.get("type") == "user":
            content = (event.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        snippet = _tool_result_text(block.get("content"))
                        if snippet:
                            await progress.add("   ↳ " + snippet)

    async def _deliver(self, ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, result: RunResult) -> None:
        text = result.text or ""
        if result.is_error and not text:
            text = "Claude gagal tanpa pesan."
            if result.stderr_tail:
                text += "\n\n" + result.stderr_tail[-1500:]
        text, file_refs = extract_files(text)
        body, question = extract_question(text)
        chunks = split_message(body) if body else []

        denial_note = format_denials(result.permission_denials)
        grant_options = options_for(result.permission_denials)

        for chunk in chunks:
            await ctx.bot.send_message(chat_id, chunk)

        await self._send_files(ctx, chat_id, file_refs)

        if question:
            ctx.chat_data.pop("pending_options", None)
            await ctx.bot.send_message(
                chat_id,
                f"❓ {question.question}\n✍️ Pilih tombol atau ketik jawabanmu sendiri.",
                reply_markup=self._ask_markup(ctx, question),
            )

        if denial_note:
            ctx.chat_data["pending_grants"] = [list(o.rules) for o in grant_options]
            rows = [
                [InlineKeyboardButton(o.label[:60], callback_data=f"grant:{i}")]
                for i, o in enumerate(grant_options)
            ]
            rows.append([InlineKeyboardButton("Abaikan", callback_data="dismiss:")])
            await ctx.bot.send_message(
                chat_id,
                denial_note,
                reply_markup=InlineKeyboardMarkup(rows) if grant_options else None,
            )

    async def _send_files(self, ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, refs: list[FileRef]) -> None:
        if not refs:
            return
        if not self.cfg.send_files:
            await ctx.bot.send_message(chat_id, "⚠️ Claude mencoba mengirim file, tetapi SEND_FILES=false.")
            return
        for ref in refs[:MAX_FILES_PER_REPLY]:
            try:
                path = resolve_sendable(
                    ref.path,
                    workdir=self.cfg.workdir,
                    roots=self.cfg.send_roots,
                    max_bytes=self.cfg.send_max_mb * 1024 * 1024,
                )
            except SendError as exc:
                log.warning("Pengiriman file ditolak: %s (%s)", ref.path, exc)
                await ctx.bot.send_message(chat_id, f"⚠️ Tidak mengirim {Path(ref.path).name}: {exc}")
                continue
            try:
                await self._send_one(ctx, chat_id, path, ref.caption or None)
            except TelegramError as exc:
                log.warning("Telegram gagal menerima %s: %s", path.name, exc)
                await ctx.bot.send_message(chat_id, f"⚠️ Gagal mengirim {path.name}: {exc}")
        if len(refs) > MAX_FILES_PER_REPLY:
            await ctx.bot.send_message(
                chat_id, f"ℹ️ {len(refs) - MAX_FILES_PER_REPLY} file lagi tidak dikirim (maks {MAX_FILES_PER_REPLY} per balasan)."
            )

    @staticmethod
    async def _send_one(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, path: Path, caption: str | None) -> None:
        """Foto/video dikirim sebagai media; bila Telegram menolak formatnya, kirim sebagai dokumen."""
        with path.open("rb") as fh:
            try:
                if is_photo(path):
                    await ctx.bot.send_photo(chat_id, fh, caption=caption)
                    return
                if is_video(path):
                    await ctx.bot.send_video(
                        chat_id, fh, caption=caption, supports_streaming=True, filename=path.name
                    )
                    return
            except TelegramError as exc:
                if not (is_photo(path) or is_video(path)):
                    raise
                log.info("Kirim sebagai media gagal (%s), mencoba sebagai dokumen", exc)
                fh.seek(0)
            await ctx.bot.send_document(chat_id, fh, filename=path.name, caption=caption)

    # ---------- file masuk dari user ----------

    @staticmethod
    def _pick_attachment(msg: Any) -> tuple[Any, str | None, str] | None:
        if msg.photo:
            return msg.photo[-1], "foto.jpg", "foto"
        if msg.document:
            return msg.document, msg.document.file_name, "dokumen"
        if msg.voice:
            return msg.voice, "voice.ogg", "pesan suara"
        if msg.audio:
            return msg.audio, msg.audio.file_name or "audio.mp3", "audio"
        if msg.video:
            return msg.video, msg.video.file_name or "video.mp4", "video"
        if msg.video_note:
            return msg.video_note, "video-note.mp4", "video note"
        return None

    async def on_file(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return await self._deny(update)
        msg = update.effective_message
        chat_id = update.effective_chat.id
        if not self.store.get(chat_id).active:
            return await msg.reply_text("Sesi Claude belum aktif. Kirim /start_claude dulu.")
        picked = self._pick_attachment(msg)
        if picked is None:
            return
        obj, name, kind = picked
        limit = self.cfg.upload_max_mb * 1024 * 1024
        if (obj.file_size or 0) > limit:
            return await msg.reply_text(
                f"⚠️ File terlalu besar ({(obj.file_size or 0) // (1024 * 1024)} MB). Batas {self.cfg.upload_max_mb} MB."
            )
        target = inbox_target(self.cfg.inbox_dir, name, fallback=kind.replace(" ", "-"))
        try:
            tg_file = await obj.get_file()
            await tg_file.download_to_drive(custom_path=target)
        except TelegramError as exc:
            log.warning("Gagal mengunduh file dari Telegram: %s", exc)
            return await msg.reply_text(f"⚠️ Gagal mengunduh file: {exc}")
        entry = (target, kind)
        caption = (msg.caption or "").strip()

        group = msg.media_group_id
        if group:  # album: kumpulkan sebentar agar jadi satu prompt
            albums = ctx.bot_data.setdefault("albums", {})
            first = group not in albums
            album = albums.setdefault(group, {"files": [], "caption": ""})
            album["files"].append(entry)
            album["caption"] = album["caption"] or caption
            if first:
                asyncio.create_task(self._flush_album(ctx, chat_id, group))
            return
        await self.run_prompt(ctx, chat_id, self.build_file_prompt([entry], caption))

    async def _flush_album(self, ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, group: str) -> None:
        await asyncio.sleep(1.5)
        album = ctx.bot_data.get("albums", {}).pop(group, None)
        if album:
            await self.run_prompt(ctx, chat_id, self.build_file_prompt(album["files"], album["caption"]))

    @staticmethod
    def build_file_prompt(files: list[tuple[Path, str]], caption: str) -> str:
        lines = [f"- {path} ({kind})" for path, kind in sorted(files, key=lambda f: str(f[0]))]
        head = "Pengguna mengirim file berikut lewat Telegram:\n" + "\n".join(lines)
        if caption:
            return f"{head}\n\nPesan pengguna: {caption}"
        return head + "\n\nPengguna tidak menulis instruksi. Periksa isinya, ringkas singkat, lalu tanyakan apa yang diinginkan."

    def _ask_markup(self, ctx: ContextTypes.DEFAULT_TYPE, q: Question) -> InlineKeyboardMarkup | None:
        if not q.options:
            return None
        ctx.chat_data["pending_options"] = list(q.options)
        rows = [
            [InlineKeyboardButton(button_label(opt), callback_data=f"ask:{i}")]
            for i, opt in enumerate(q.options)
        ]
        return InlineKeyboardMarkup(rows)

    # ---------- setup ----------

    def register(self, app: Application) -> None:
        app.add_handler(CommandHandler(["start", "help"], self.cmd_help))
        app.add_handler(CommandHandler("id", self.cmd_id))
        app.add_handler(CommandHandler("login", self.cmd_login))
        app.add_handler(CommandHandler("logout", self.cmd_logout))
        app.add_handler(CommandHandler("start_claude", self.cmd_start_claude))
        app.add_handler(CommandHandler("end_claude", self.cmd_end_claude))
        app.add_handler(CommandHandler("new", self.cmd_new))
        app.add_handler(CommandHandler("stop", self.cmd_stop))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(CommandHandler("mode", self.cmd_mode))
        app.add_handler(CommandHandler("model", self.cmd_model))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_handler(
            MessageHandler(
                filters.PHOTO
                | filters.Document.ALL
                | filters.VOICE
                | filters.AUDIO
                | filters.VIDEO
                | filters.VIDEO_NOTE,
                self.on_file,
            )
        )

    @staticmethod
    async def post_init(app: Application) -> None:
        await app.bot.set_my_commands(
            [
                BotCommand("login", "Buka kunci dengan kode 2FA"),
                BotCommand("logout", "Kunci kembali"),
                BotCommand("start_claude", "Mulai sesi Claude"),
                BotCommand("end_claude", "Akhiri sesi Claude"),
                BotCommand("new", "Percakapan baru"),
                BotCommand("stop", "Batalkan proses berjalan"),
                BotCommand("status", "Info sesi"),
                BotCommand("mode", "Ganti permission mode"),
                BotCommand("model", "Ganti model"),
                BotCommand("help", "Bantuan"),
            ]
        )


def _tool_result_text(content: Any, limit: int = 200) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = " ".join(
            str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    else:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def _typing_loop(bot: Any, chat_id: int) -> None:
    try:
        while True:
            try:
                await bot.send_chat_action(chat_id, ChatAction.TYPING)
            except TelegramError:
                pass
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


class _Progress:
    """Satu pesan 'sedang bekerja' yang diedit seiring tool dipakai."""

    def __init__(self, bot: Any, chat_id: int, enabled: bool):
        self._bot = bot
        self._chat_id = chat_id
        self._enabled = enabled
        self._msg = None
        self._lines: list[str] = []
        self._last_edit = 0.0
        self._last_text = ""

    async def start(self) -> None:
        if self._enabled:
            self._msg = await self._bot.send_message(self._chat_id, "⏳ Claude bekerja…")

    def _render(self, header: str) -> str:
        body = "\n".join(self._lines[-PROGRESS_LINES:])
        return f"{header}\n{body}".strip()[:4000]

    async def _edit(self, text: str) -> None:
        if self._msg is None or text == self._last_text:
            return
        try:
            await self._msg.edit_text(text)
            self._last_text = text
        except BadRequest as exc:
            if "not modified" not in str(exc).lower():
                log.debug("edit progress gagal: %s", exc)
        except TelegramError as exc:
            log.debug("edit progress gagal: %s", exc)

    async def add(self, line: str) -> None:
        self._lines.append(line)
        now = time.monotonic()
        if now - self._last_edit >= EDIT_INTERVAL:
            self._last_edit = now
            await self._edit(self._render("⏳ Claude bekerja…"))

    async def finish(self, footer: str) -> None:
        if self._msg is None:
            return
        self._last_text = ""
        await self._edit(self._render(footer))
