"""Deliver the owner's Windows installer as a document, then reuse its Telegram ID."""

import asyncio
import hashlib
from functools import lru_cache
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

from app.bot.texts import ru
from app.db.session import sessions
from app.services.settings import set_setting, setting

WINDOWS_INSTALLER = (
    Path(__file__).resolve().parents[1] / "assets" / "installers" / "Hiddify-Windows-Setup-x64.exe"
)
_upload_lock = asyncio.Lock()


@lru_cache(maxsize=4)
def installer_digest(path, modified_ns, size):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


async def send_windows_installer(message, *, caption=None, unavailable=None):
    caption = caption or ru.WINDOWS_INSTALLER_CAPTION
    try:
        info = WINDOWS_INSTALLER.stat()
        digest = await asyncio.to_thread(
            installer_digest, str(WINDOWS_INSTALLER), info.st_mtime_ns, info.st_size
        )
    except OSError:
        await message.answer(unavailable or ru.WINDOWS_INSTALLER_UNAVAILABLE)
        return
    key = f"hiddify_windows:{message.bot.id}:{digest}"
    async with _upload_lock:
        async with sessions() as db:
            file_id = await setting(db, key)
        if file_id:
            try:
                await message.answer_document(file_id, caption=caption, parse_mode=None)
                return
            except TelegramBadRequest as error:
                if not any(
                    reason in error.message.lower()
                    for reason in ("file identifier", "file_id", "wrong remote file")
                ):
                    raise
                async with sessions.begin() as db:
                    await set_setting(db, key, "")
        result = await message.answer_document(
            FSInputFile(WINDOWS_INSTALLER),
            caption=caption,
            parse_mode=None,
            request_timeout=180,
        )
        if result.document:
            async with sessions.begin() as db:
                await set_setting(db, key, result.document.file_id)
