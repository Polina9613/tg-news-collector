from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from loguru import logger

from db.base import get_session
from db.models import BotUser

COMMANDS_ANALYST = [
    BotCommand(command="start",       description="Регистрация"),
    BotCommand(command="menu",        description="Главное меню"),
    BotCommand(command="help",        description="Справка"),
    BotCommand(command="search",      description="Поиск по кейсам"),
    BotCommand(command="company",     description="Поиск по компании"),
    BotCommand(command="topic",       description="Поиск по теме"),
    BotCommand(command="trends",      description="Все тренды"),
    BotCommand(command="export",      description="Excel-выгрузка"),
    BotCommand(command="digest_now",  description="Последний дайджест"),
    BotCommand(command="stats",       description="Статистика"),
    BotCommand(command="excel_guide", description="Описание Excel"),
]

COMMANDS_ADMIN = COMMANDS_ANALYST + [
    BotCommand(command="review_week",      description="Кейсы недели с фильтрами"),
    BotCommand(command="review",           description="Кейсы на проверку"),
    BotCommand(command="pending_trends",   description="Тренды на модерации"),
    BotCommand(command="add",              description="Добавить кейс"),
    BotCommand(command="channel_stats",    description="Статистика каналов"),
    BotCommand(command="channels",         description="Управление каналами"),
    BotCommand(command="users",            description="Список пользователей"),
    BotCommand(command="collect",          description="Сбор постов"),
    BotCommand(command="process",          description="Обработка постов"),
    BotCommand(command="enrich",           description="LLM-обогащение"),
    BotCommand(command="digest",           description="Сгенерировать дайджест"),
    BotCommand(command="broadcast_digest", description="Рассылка дайджеста"),
]

_ROLE_COMMANDS = {
    "admin":   COMMANDS_ADMIN,
    "analyst": COMMANDS_ANALYST,
}


async def set_default_commands(bot: Bot) -> None:
    """Базовые команды для незарегистрированных пользователей (синяя кнопка Menu)."""
    await bot.set_my_commands(COMMANDS_ANALYST, scope=BotCommandScopeDefault())
    logger.info("Default bot commands set")


async def update_user_commands(bot: Bot, telegram_id: int, role: str) -> None:
    """Персональное меню для пользователя по его роли."""
    commands = COMMANDS_ADMIN if role == "admin" else COMMANDS_ANALYST
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=telegram_id))
    except Exception as e:
        logger.warning(f"Failed to set commands for tg={telegram_id}: {e}")


async def refresh_all_user_commands(bot: Bot) -> None:
    """Обновляет персональные меню всех активных пользователей при старте бота."""
    with get_session() as s:
        data = [(u.telegram_id, u.role) for u in s.query(BotUser).filter_by(is_active=True).all()]
    for tg_id, role in data:
        await update_user_commands(bot, tg_id, role)
    logger.info(f"Refreshed commands for {len(data)} users")
