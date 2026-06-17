import json

from db.base import get_session
from db.models import AuditLog


def log_action(
    user_id: int,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    payload: dict | None = None,
) -> None:
    """Логирует действие пользователя в audit_log."""
    with get_session() as session:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=json.dumps(payload, ensure_ascii=False) if payload else None,
        )
        session.add(entry)
