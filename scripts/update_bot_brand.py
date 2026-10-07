"""Update the avatar; preserve owner-written profile copy unless explicitly requested."""

import argparse
import asyncio
import logging
from pathlib import Path

from aiogram.types import FSInputFile, InputProfilePhotoStatic

from app.bot.client import create_bot
from app.config import get_settings


def short_dashes(value):
    return value.replace("—", "-").replace("–", "-")


async def main(options):
    settings = get_settings()
    bot = create_bot(settings)
    try:
        identity = await bot.get_me()
        if identity.username.casefold() != settings.bot_username.casefold():
            raise RuntimeError("Bot identity mismatch")
        original_name = (await bot.get_my_name()).name
        if options.name:
            assert await bot.set_my_name(options.name)
            assert (await bot.get_my_name()).name == options.name
        if options.short_dashes:
            description = short_dashes((await bot.get_my_description()).description)
            about = short_dashes((await bot.get_my_short_description()).short_description)
            assert await bot.set_my_description(description)
            assert await bot.set_my_short_description(about)
            assert (await bot.get_my_description()).description == description
            assert (await bot.get_my_short_description()).short_description == about
        image = Path(__file__).resolve().parents[1] / options.avatar
        assert await bot.set_my_profile_photo(InputProfilePhotoStatic(photo=FSInputFile(image)))
        photos = await bot.get_user_profile_photos(identity.id, limit=1)
        assert photos.total_count > 0
        if not options.name:
            assert (await bot.get_my_name()).name == original_name
        print("Requested AERA profile changes applied and verified")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avatar", default="app/assets/ui/avatar-v2.png")
    parser.add_argument("--name", help="Only change the name when explicitly supplied")
    parser.add_argument("--short-dashes", action="store_true", help="Only replace long dashes")
    arguments = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        asyncio.run(main(arguments))
    except Exception as error:
        print(f"Brand update stopped: {type(error).__name__}")
        raise SystemExit(1) from None
