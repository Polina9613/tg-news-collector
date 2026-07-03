from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from loguru import logger

from db.base import get_session
from db.models import BotUser


# ── Команды аналитика (видны всем) ────────────────────────────────────────
COMMANDS_ANALYST = [
    # Базовые
    BotCommand(command="start",        description="Регистрация"),
    BotCommand(command="menu",         description="Главное меню"),
    BotCommand(command="help",         description="Справка по командам"),

    # Поиск
    BotCommand(command="search",       description="Поиск по кейсам"),
    BotCommand(command="company",      description="Кейсы по компании"),
    BotCommand(command="topic",        description="Кейсы по теме"),

    # Тренды
    BotCommand(command="trends",       description="Все 22 тренда"),
    BotCommand(command="trend",        description="Детали тренда: /trend 5"),
    BotCommand(command="search_trend", description="Кейсы тренда: /search_trend 5"),

    # Исследование
    BotCommand(command="research",     description='Исследование: /research "тема"'),

    # Данные
    BotCommand(command="export",       description="Excel: /export 7|30|all"),
    BotCommand(command="digest_now",   description="Последний дайджест"),
    BotCommand(command="stats",        description="Статистика базы"),

    # Документация
    BotCommand(command="excel_guide",  description="Описание Excel-файла"),
    BotCommand(command="user_guide",   description="Руководство пользователя"),
]

# ── Дополнительные команды для администратора ─────────────────────────────
COMMANDS_ADMIN_EXTRA = [
    # Модерация
    BotCommand(command="review_week",     description="Кейсы с фильтрами"),
    BotCommand(command="pending_trends",  description="Тренды на модерации"),
    BotCommand(command="edit",            description="Редактировать кейс: /edit 42"),
    BotCommand(command="add",             description="Добавить кейс вручную"),

    # Каналы
    BotCommand(command="channels",        description="Список каналов"),
    BotCommand(command="channel_stats",   description="Статистика каналов"),
    BotCommand(command="add_channel",     description="Добавить канал"),
    BotCommand(command="toggle_channel",  description="Вкл/выкл канал"),
    BotCommand(command="remove_channel",  description="Удалить канал"),

    # Пайплайн
    BotCommand(command="collect",         description="Сбор постов"),
    BotCommand(command="process",         description="Обработка постов"),
    BotCommand(command="enrich",          description="LLM-обогащение"),
    BotCommand(command="digest",          description="Сгенерировать дайджест"),
    BotCommand(command="broadcast_digest",description="Разослать дайджест"),

    # Пользователи
    BotCommand(command="users",           description="Список пользователей"),
    BotCommand(command="promote",         description="Повысить до админа"),
    BotCommand(command="demote",          description="Понизить до аналитика"),

    # Утилиты
    BotCommand(command="refresh_menu",    description="Обновить меню у всех"),
]


async def set_bot_commands(bot: Bot) -> None:
    """Устанавливает команды для всех ролей."""
    await bot.set_my_commands(COMMANDS_ANALYST, scope=BotCommandScopeDefault())

    with get_session() as s:
        admins = s.query(BotUser).filter_by(role="admin", is_active=True).all()
        admin_ids = [a.telegram_id for a in admins]

    for tg_id in admin_ids:
        try:
            await bot.set_my_commands(
                COMMANDS_ANALYST + COMMANDS_ADMIN_EXTRA,
                scope=BotCommandScopeChat(chat_id=tg_id),
            )
        except Exception as e:
            logger.warning(f"Failed to set admin commands for {tg_id}: {e}")

    logger.info(
        f"Default bot commands set | "
        f"Refreshed commands for {len(admin_ids)} admin(s)"
    )


async def set_user_commands(bot: Bot, telegram_id: int, role: str) -> None:
    """Устанавливает меню для конкретного пользователя (promote / demote / start)."""
    commands = COMMANDS_ANALYST + COMMANDS_ADMIN_EXTRA if role == "admin" else COMMANDS_ANALYST
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=telegram_id))
    except Exception as e:
        logger.warning(f"Failed to set commands for {telegram_id}: {e}")
