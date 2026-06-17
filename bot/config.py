from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import get_settings


def create_bot() -> Bot:
    settings = get_settings()
    if not settings.bot_token:
        raise ValueError("BOT_TOKEN не задан в .env")
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    from bot.handlers import (
        admin, analyst, channels, editor, guide, menu, pipeline, start,
        trends_moderation,
    )
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(pipeline.router)
    dp.include_router(trends_moderation.router)
    dp.include_router(editor.router)
    dp.include_router(analyst.router)
    dp.include_router(channels.router)
    dp.include_router(guide.router)
    dp.include_router(menu.router)

    return dp
