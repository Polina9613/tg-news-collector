import asyncio

from loguru import logger

from bot.config import create_bot, create_dispatcher
from bot.menu import set_bot_commands
from bot.scheduler import setup_scheduler
from config.settings import setup_logging
from db.init_db import init_db


async def main() -> None:
    setup_logging()
    init_db()

    bot = create_bot()
    dp = create_dispatcher()

    scheduler = setup_scheduler(bot)

    await set_bot_commands(bot)

    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username}")

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
