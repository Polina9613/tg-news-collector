from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from loguru import logger

from bot.menu import update_user_commands
from bot.users import get_or_create_user, get_user_by_tg_id

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    logger.info(f"User /start: tg={user['telegram_id']} role={user['role']}")
    await update_user_commands(message.bot, user["telegram_id"], user["role"])

    name = user["first_name"] or user["username"] or "коллега"

    if user["role"] == "admin":
        text = (
            f"👋 Привет, {name}! Ты администратор.\n\n"
            "/menu — главное меню\n"
            "/help — все команды"
        )
    else:
        text = (
            f"👋 Привет, {name}!\n\n"
            "Ты аналитик — у тебя есть доступ к поиску по базе кейсов, "
            "трендам и Excel-выгрузке.\n\n"
            "/menu — главное меню\n"
            "/help — все команды\n\n"
            "Если ты администратор системы:\n"
            "/admin &lt;кодовое_слово&gt;"
        )

    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    user = get_user_by_tg_id(message.from_user.id)
    role = user["role"] if user else "analyst"

    analyst_cmds = (
        "🔍 <b>Поиск по базе знаний:</b>\n"
        "/search &lt;текст&gt; — поиск по содержимому\n"
        "/company &lt;название&gt; — кейсы по компании\n"
        "/topic &lt;тема&gt; [дней] — кейсы по теме\n"
        "  Пример: /topic ИИ 30\n"
        "/trends — список всех трендов\n"
        "/trend &lt;id&gt; — детали тренда\n"
        "/search_trend &lt;id&gt; — все кейсы тренда\n\n"
        "📊 <b>Экспорт:</b>\n"
        "/export 7|30|all — Excel-выгрузка\n"
        "/digest_now — последний дайджест\n"
        "/stats — статистика базы\n\n"
        "📖 /excel_guide — описание структуры Excel\n"
    )

    admin_cmds = (
        "\n⚙️ <b>Управление парсером:</b>\n"
        "/collect [дней] — сбор постов\n"
        "/process — обработка\n"
        "/enrich [лимит] — LLM-обогащение\n"
        "/digest [дней] — сгенерировать дайджест\n\n"
        "🆕 <b>Модерация трендов:</b>\n"
        "/pending_trends — тренды на модерации\n\n"
        "📋 <b>Редактор кейсов:</b>\n"
        "/review_week — все кейсы за период с фильтрами\n"
        "/edit &lt;id&gt; — редактировать кейс по ID\n"
        "/review — старый редактор (только needs_review)\n"
        "/add — добавить кейс вручную\n\n"
        "📡 <b>Управление каналами:</b>\n"
        "/channels — список каналов\n"
        "/channel_stats — сводка по всем каналам\n"
        "/channel_stats @username — детали канала\n"
        "/add_channel — добавить\n"
        "/toggle_channel @username — вкл/выкл\n"
        "/remove_channel @username — удалить\n\n"
        "👥 <b>Пользователи:</b>\n"
        "/users — список\n"
        "/promote @username — повысить до администратора\n"
        "/demote @username — понизить до аналитика\n\n"
        "📣 /broadcast_digest — рассылка дайджеста сейчас\n"
    )

    if role == "admin":
        await message.answer(analyst_cmds + admin_cmds)
    else:
        await message.answer(analyst_cmds)
