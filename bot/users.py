from datetime import datetime

from loguru import logger
from sqlalchemy import func

from db.base import get_session
from db.models import BotUser


def get_or_create_user(
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> dict:
    """Находит или создаёт пользователя. Возвращает dict чтобы избежать DetachedInstanceError."""
    with get_session() as session:
        user = session.query(BotUser).filter_by(telegram_id=telegram_id).first()
        if user:
            if username and user.username != username:
                logger.info(f"User tg={telegram_id} username updated: {user.username!r} → {username!r}")
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.last_active_at = datetime.utcnow()
            session.flush()
        else:
            user = BotUser(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                role="analyst",
            )
            session.add(user)
            session.flush()
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "role": user.role,
            "is_active": user.is_active,
        }


def get_user_by_tg_id(telegram_id: int) -> dict | None:
    with get_session() as session:
        user = session.query(BotUser).filter_by(telegram_id=telegram_id).first()
        if not user:
            return None
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "role": user.role,
            "is_active": user.is_active,
        }


def get_user_by_username(username: str) -> dict | None:
    """Поиск по @username (case-insensitive)."""
    username = username.lstrip("@").lower()
    with get_session() as session:
        user = session.query(BotUser).filter(
            func.lower(BotUser.username) == username
        ).first()
        if not user:
            return None
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "role": user.role,
        }


def set_role(telegram_id: int, role: str) -> bool:
    """Меняет роль пользователя. Возвращает True если успешно."""
    assert role in ("admin", "analyst")
    with get_session() as session:
        user = session.query(BotUser).filter_by(telegram_id=telegram_id).first()
        if not user:
            return False
        user.role = role
        return True


def list_users(role: str | None = None) -> list[dict]:
    with get_session() as session:
        q = session.query(BotUser)
        if role:
            q = q.filter_by(role=role)
        users = q.order_by(BotUser.joined_at.desc()).all()
        return [
            {
                "id": u.id,
                "telegram_id": u.telegram_id,
                "username": u.username,
                "first_name": u.first_name,
                "role": u.role,
                "joined_at": u.joined_at.strftime("%d.%m.%Y"),
            }
            for u in users
        ]


def count_admins() -> int:
    with get_session() as session:
        return session.query(BotUser).filter_by(role="admin").count()
