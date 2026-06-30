from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from db.base import get_session
from db.models import BotUser


async def notify_admins_about_pdf(
    bot: Bot,
    channel_username: str,
    channel_title: str,
    filename: str,
    post_url: str,
    post_text: str,
) -> None:
    """Send a PDF discovery notification with Yes/No inline buttons to all active admins."""
    safe_name = filename[:50].replace(":", "-")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Добавить в базу", callback_data=f"pdf:yes:{safe_name}"),
        InlineKeyboardButton(text="❌ Пропустить", callback_data="pdf:no"),
    ]])

    text = (
        f"📄 <b>Новый PDF-документ</b>\n\n"
        f"Канал: {channel_title} ({channel_username})\n"
        f"Файл: <code>{filename}</code>\n\n"
        f"<a href='{post_url}'>Открыть пост</a>"
    )
    if post_text:
        text += f"\n\n<i>{post_text[:300]}</i>"

    with get_session() as s:
        admin_ids = [
            u.telegram_id
            for u in s.query(BotUser).filter_by(role="admin", is_active=True).all()
        ]

    for tg_id in admin_ids:
        try:
            await bot.send_message(tg_id, text, reply_markup=kb)
        except Exception as e:
            logger.warning(f"[pdf_notifier] Failed to notify admin {tg_id}: {e}")
