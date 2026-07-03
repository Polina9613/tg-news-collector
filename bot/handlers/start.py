from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from loguru import logger

from bot.menu import set_user_commands
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
    await set_user_commands(message.bot, user["telegram_id"], user["role"])

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

    analyst_text = (
        "📖 <b>Руководство пользователя:</b> /user_guide\n\n"

        "🔍 <b>Поиск по базе знаний:</b>\n"
        "/search &lt;текст&gt; — поиск по содержимому кейсов\n"
        "/company &lt;название&gt; — все кейсы компании\n"
        "/topic &lt;тема&gt; [дней] — кейсы по теме\n\n"

        "📈 <b>Тренды:</b>\n"
        "/trends — все 22 канонических тренда\n"
        "/trend &lt;id&gt; — детали тренда\n"
        "/search_trend &lt;id&gt; — все кейсы тренда\n\n"

        "🔬 <b>Исследование по теме:</b>\n"
        "/research \"тема\" — исследование на основе базы кейсов\n"
        "/research \"тема\" 90 — за последние 90 дней\n\n"

        "📊 <b>Данные и экспорт:</b>\n"
        "/export 7|30|all — Excel-выгрузка за период\n"
        "/digest_now — последний еженедельный дайджест\n"
        "/stats — статистика базы\n"
        "/excel_guide — описание структуры Excel\n"
    )

    admin_text = (
        "\n✏️ <b>Модерация кейсов:</b>\n"
        "/review_week — все кейсы с фильтрами по статусу и дате\n"
        "/edit &lt;id&gt; — редактировать кейс по ID\n"
        "/add — добавить кейс вручную\n\n"

        "🆕 <b>Модерация трендов:</b>\n"
        "/pending_trends — тренды предложенные LLM (✅ ❌ ✏️ ↔️)\n\n"

        "📡 <b>Каналы:</b>\n"
        "/channels — список всех каналов\n"
        "/channel_stats [@username] — статистика\n"
        "/add_channel — добавить канал\n"
        "/toggle_channel @username — вкл/выкл\n"
        "/remove_channel @username — удалить\n\n"

        "⚙️ <b>Pipeline:</b>\n"
        "/collect [дней] — сбор постов вручную\n"
        "/process — обработка постов\n"
        "/enrich [лимит] — LLM-обогащение\n"
        "/digest [дней] — сгенерировать дайджест\n"
        "/broadcast_digest — разослать дайджест всем\n\n"

        "👥 <b>Пользователи:</b>\n"
        "/users — список\n"
        "/promote @username — повысить до администратора\n"
        "/demote @username — понизить до аналитика\n\n"

        "🔧 /refresh_menu — обновить меню команд у всех пользователей\n"
    )

    await message.answer(
        analyst_text + (admin_text if role == "admin" else "")
    )


@router.message(Command("user_guide"))
async def cmd_user_guide(message: Message) -> None:
    text = (
        "📖 <b>Краткое руководство пользователя</b>\n\n"
        "<b>Поиск кейсов:</b>\n"
        "/search <i>ключевые слова</i> — полнотекстовый поиск\n"
        "/company <i>название</i> — все кейсы одной компании\n"
        "/topic <i>тема</i> [дней] — кейсы по теме за период\n\n"
        "<b>Тренды:</b>\n"
        "/trends — список всех 22 трендов с ID\n"
        "/trend <i>id</i> — описание тренда и свежие кейсы\n"
        "/search_trend <i>id</i> — полная история кейсов тренда\n\n"
        "<b>Исследования:</b>\n"
        '/research "тема" — LLM-исследование на базе кейсов\n'
        '/research "тема" 90 — за последние 90 дней\n\n'
        "<b>Экспорт:</b>\n"
        "/export 7 — Excel за последние 7 дней\n"
        "/export 30 — за 30 дней\n"
        "/export all — вся база\n"
        "/excel_guide — описание столбцов Excel\n\n"
        "<b>Дайджест:</b>\n"
        "/digest_now — последний еженедельный дайджест\n\n"
        "/stats — статистика базы кейсов\n"
    )
    await message.answer(text)
