from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import RawPost
from processor.cleaner import compute_hash  # noqa: F401  re-exported

__all__ = ["compute_hash", "is_duplicate"]


def is_duplicate(session: Session, source_id: int, message_id: int) -> bool:
    row = session.execute(
        select(RawPost.id).where(
            RawPost.source_id == source_id,
            RawPost.message_id == message_id,
        )
    ).first()
    return row is not None
