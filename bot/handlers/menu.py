from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.users import get_user_by_tg_id

router = Router()


def _menu_analyst() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Поиск",        callback_data="m:search"),
            InlineKeyboardButton(text="📈 Тренды",        callback_data="m:trends"),
            InlineKeyboardButton(text="📊 Статистика",    callback_data="m:stats"),
        ],
        [
            InlineKeyboardButton(text="🔬 Исследование",  callback_data="m:research"),
            InlineKeyboardButton(text="📰 Дайджест",      callback_data="m:digest"),
        ],
        [
            InlineKeyboardButton(text="📁 Excel",          callback_data="m:export"),
            InlineKeyboardButton(text="📖 Справка",        callback_data="m:help"),
        ],
    ])


def _menu_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Поиск",         callback_data="m:search"),
            InlineKeyboardButton(text="📈 Тренды",         callback_data="m:trends"),
            InlineKeyboardButton(text="📊 Статистика",     callback_data="m:stats"),
        ],
        [
            InlineKeyboardButton(text="🔬 Исследование",   callback_data="m:research"),
            InlineKeyboardButton(text="📰 Дайджест",       callback_data="m:digest"),
            InlineKeyboardButton(text="📁 Excel",           callback_data="m:export"),
        ],
        [
            InlineKeyboardButton(text="✏️ Review",         callback_data="m:review"),
            InlineKeyboardButton(text="➕ Add case",        callback_data="m:add"),
        ],
        [
            InlineKeyboardButton(text="📡 Каналы",          callback_data="m:channels"),
            InlineKeyboardButton(text="👥 Пользователи",    callback_data="m:users"),
        ],
        [
            InlineKeyboardButton(text="📨 Рассылка",        callback_data="m:broadcast"),
            InlineKeyboardButton(text="📖 Excel guide",     callback_data="m:guide"),
        ],
        [
            InlineKeyboardButton(text="❓ Справка",          callback_data="m:help"),
        ],
    ])


MENU_ACTIONS: dict[str, str] = {
    "search": (
        "🔍 <b>Поиск кейсов</b>\n"
        "<code>/search текст</code>\n"
        "<code>/company название</code>\n"
        "<code>/topic тема</code>"
    ),
    "trends": (
        "📈 <b>Тренды</b>\n"
        "/trends — все 22 тренда\n"
        "/trend &lt;id&gt; — детали тренда\n"
        "/search_trend &lt;id&gt; — кейсы тренда"
    ),
    "stats":     "📊 Статистика базы: /stats",
    "research":  '🔬 Исследование: /research "тема"',
    "digest":    "📰 Последний дайджест: /digest_now",
    "export":    "📁 Excel-экспорт:\n<code>/export 7</code> или <code>/export all</code>",
    "help":      "❓ Полная справка: /help",
    "review":    "✏️ Проверка кейсов недели: /review_week",
    "add":       "➕ Добавить кейс вручную: /add",
    "channels":  "📡 Управление каналами: /channels",
    "users":     "👥 Список пользователей: /users",
    "broadcast": "📨 Рассылка дайджеста: /broadcast_digest",
    "guide":     "📖 Описание Excel: /excel_guide",
}


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    user = get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала /start")
        return

    if user["role"] == "admin":
        kb = _menu_admin()
        text = "👑 <b>Главное меню — администратор</b>"
    else:
        kb = _menu_analyst()
        text = "🔬 <b>Главное меню — аналитик</b>"

    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("m:"))
async def handle_menu_action(call: CallbackQuery) -> None:
    action = call.data.split(":", 1)[1]
    text = MENU_ACTIONS.get(action, "Неизвестное действие")
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()
