from functools import wraps

from aiogram.types import Message

from bot.users import get_user_by_tg_id


def require_role(*allowed_roles: str):
    """Декоратор: разрешает выполнение только пользователям с указанными ролями."""
    def decorator(handler):
        @wraps(handler)
        async def wrapper(message: Message, *args, **kwargs):
            user = get_user_by_tg_id(message.from_user.id)
            if not user:
                await message.answer("Сначала запустите бота командой /start")
                return
            if user["role"] not in allowed_roles:
                role_names = {
                    "admin": "администратора",
                    "analyst": "аналитика",
                }
                needed = " или ".join(role_names.get(r, r) for r in allowed_roles)
                await message.answer(f"Команда доступна только для роли: {needed}")
                return
            return await handler(message, *args, **kwargs)
        return wrapper
    return decorator
