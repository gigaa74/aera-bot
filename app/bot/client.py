"""Alternative aiogram transport for environments where aiohttp cannot connect."""

from contextlib import ExitStack
from tempfile import SpooledTemporaryFile

import httpx
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramNetworkError


class HttpxSession(BaseSession):
    def __init__(self, transport=None):
        super().__init__()
        self.http = httpx.AsyncClient(transport=transport, follow_redirects=False)

    async def close(self):
        await self.http.aclose()

    async def make_request(self, bot, method, timeout=None):
        attachments, fields = {}, {}
        for key, value in method.model_dump(warnings=False).items():
            prepared = self.prepare_value(value, bot=bot, files=attachments)
            if prepared is not None:
                fields[key] = prepared
        # Keep large documents off the heap on the resource-limited bot VPS.
        with ExitStack() as stack:
            files = {}
            for key, attachment in attachments.items():
                content = stack.enter_context(SpooledTemporaryFile(max_size=1024**2))
                size = 0
                async for chunk in attachment.read(bot):
                    size += len(chunk)
                    if size > 50 * 1024**2:
                        raise TelegramNetworkError(
                            method=method, message="Upload exceeds local limit"
                        )
                    content.write(chunk)
                content.seek(0)
                files[key] = (attachment.filename or key, content)
            try:
                result = await self.http.post(
                    self.api.api_url(token=bot.token, method=method.__api_method__),
                    data=fields,
                    files=files or None,
                    timeout=self.timeout if timeout is None else timeout,
                )
            except httpx.HTTPError:
                raise TelegramNetworkError(
                    method=method, message="Telegram connection failed"
                ) from None
        response = self.check_response(
            bot=bot, method=method, status_code=result.status_code, content=result.text
        )
        return response.result

    async def stream_content(
        self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True
    ):
        async with self.http.stream("GET", url, headers=headers, timeout=timeout) as response:
            if raise_for_status:
                response.raise_for_status()
            async for chunk in response.aiter_bytes(chunk_size):
                yield chunk


def create_bot(settings):
    return (
        Bot(settings.bot_token, session=HttpxSession())
        if (settings.telegram_http_client == "httpx")
        else Bot(settings.bot_token)
    )
