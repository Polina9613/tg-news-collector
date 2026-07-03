from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.audit import log_action
from bot.menu import set_bot_commands, set_user_commands
from bot.permissions import require_role
from bot.users import (
    count_admins,
    get_user_by_tg_id,
    get_user_by_username,
    list_users,
    set_role,
)
from config.settings import get_settings

router = Router()


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Получение прав админа через кодовое слово."""
    settings = get_settings()
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("Использование: /admin &lt;кодовое_слово&gt;")
        return

    secret = parts[1].strip()

    if not settings.bot_admin_secret:
        await message.answer("Админский режим не настроен в системе.")
        return

    if secret != settings.bot_admin_secret:
        await message.answer("Неверное кодовое слово.")
        logger.warning(f"Failed admin attempt by tg={message.from_user.id}")
        return

    user = get_user_by_tg_id(message.from_user.id)
    if not user:
        await message.answer("Сначала отправьте /start")
        return

    if user["role"] == "admin":
        await message.answer("Ты уже администратор.")
        return

    set_role(message.from_user.id, "admin")
    log_action(user["id"], action="self_promote_admin")
    logger.info(f"User tg={message.from_user.id} promoted to admin via secret")
    await set_user_commands(message.bot, message.from_user.id, "admin")

    await message.answer(
        "Ты теперь администратор!\n"
        "Отправь /help чтобы посмотреть доступные команды."
    )


@router.message(Command("promote"))
@require_role("admin")
async def cmd_promote(message: Message) -> None:
    """Повысить аналитика до администратора."""
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /promote @username")
        return

    target_username = parts[1].lstrip("@")
    target = get_user_by_username(target_username)

    if not target:
        await message.answer(
            f"Пользователь @{target_username} не найден.\n"
            "Он должен сначала запустить бота командой /start"
        )
        return

    if target["role"] == "admin":
        await message.answer(f"⚠️ @{target_username} уже администратор.")
        return

    set_role(target["telegram_id"], "admin")
    admin_user = get_user_by_tg_id(message.from_user.id)
    log_action(
        admin_user["id"],
        action="promote",
        target_type="user",
        target_id=target["id"],
        payload={"to": "admin"},
    )
    await set_user_commands(message.bot, target["telegram_id"], "admin")
    await message.answer(f"✅ @{target_username} теперь администратор.")


@router.message(Command("demote"))
@require_role("admin")
async def cmd_demote(message: Message) -> None:
    """Понизить администратора до аналитика."""
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /demote @username")
        return

    target_username = parts[1].lstrip("@")
    target = get_user_by_username(target_username)

    if not target:
        await message.answer(f"Пользователь @{target_username} не найден.")
        return

    if target["role"] == "analyst":
        await message.answer(f"@{target_username} уже аналитик.")
        return

    if target["role"] == "admin" and count_admins() <= 1:
        await message.answer("Нельзя понизить последнего администратора.")
        return

    if target["telegram_id"] == message.from_user.id and target["role"] == "admin":
        if count_admins() <= 1:
            await message.answer("Ты последний админ, нельзя себя понизить.")
            return

    old_role = target["role"]
    set_role(target["telegram_id"], "analyst")
    admin_user = get_user_by_tg_id(message.from_user.id)
    log_action(
        admin_user["id"],
        action="demote",
        target_type="user",
        target_id=target["id"],
        payload={"from": old_role, "to": "analyst"},
    )
    await set_user_commands(message.bot, target["telegram_id"], "analyst")
    await message.answer(f"✅ @{target_username} теперь аналитик.")


@router.message(Command("broadcast_digest"))
@require_role("admin")
async def cmd_broadcast_digest(message: Message) -> None:
    """Запустить рассылку дайджеста всем пользователям вручную."""
    await message.answer("Запускаю рассылку дайджеста...")
    from bot.scheduler import send_weekly_digest_to_all
    await send_weekly_digest_to_all(message.bot)
    await message.answer("Рассылка завершена. Подробности в логах.")


@router.message(Command("refresh_menu"))
@require_role("admin")
async def cmd_refresh_menu(message: Message) -> None:
    """Обновить меню команд Telegram для всех активных пользователей."""
    await set_bot_commands(message.bot)
    from db.base import get_session
    from db.models import BotUser
    with get_session() as s:
        count = s.query(BotUser).filter_by(is_active=True).count()
    await message.answer(
        f"✅ Меню команд обновлено.\n"
        f"Применится для {count} активных пользователей "
        f"(может занять до нескольких минут на стороне Telegram)."
    )



@router.callback_query(F.data.startswith("pdf:yes:"))
async def handle_pdf_yes(call: CallbackQuery) -> None:
    parts = call.data.split(":", 2)
    filename = parts[2] if len(parts) > 2 else "unknown.pdf"
    await call.message.edit_text(
        f"✅ <b>PDF отмечен для обработки:</b> <code>{filename}</code>\n\n"
        "Загрузите файл вручную в базу знаний или передайте аналитику."
    )
    await call.answer()


@router.callback_query(F.data == "pdf:no")
async def handle_pdf_no(call: CallbackQuery) -> None:
    await call.message.edit_text("❌ PDF пропущен.")
    await call.answer()


@router.message(Command("users"))
@require_role("admin")
async def cmd_users(message: Message) -> None:
    """Список всех пользователей бота."""
    users = list_users()
    if not users:
        await message.answer("Пользователей пока нет.")
        return

    by_role: dict[str, list] = {"admin": [], "analyst": []}
    for u in users:
        by_role.setdefault(u["role"], []).append(u)

    lines = ["Пользователи бота:\n"]
    role_titles = {
        "admin": "Администраторы",
        "analyst": "Аналитики",
    }
    for role, title in role_titles.items():
        lst = by_role.get(role, [])
        lines.append(f"\n{title} ({len(lst)}):")
        for u in lst:
            name = f"@{u['username']}" if u["username"] else u["first_name"] or "—"
            lines.append(f"  • {name} (с {u['joined_at']})")

    await message.answer("\n".join(lines))
