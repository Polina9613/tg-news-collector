from datetime import datetime, timedelta

from loguru import logger

from db.base import get_session
from db.models import NewsCard


def _word_set(text: str) -> set[str]:
    return {w.lower() for w in text.split() if len(w) >= 4}


def find_early_duplicate(
    card_text: str,
    card_id: int,
    since_hours: int = 48,
    overlap_threshold: float = 0.65,
) -> int | None:
    """
    Ищет уже обработанный NewsCard за последние since_hours с высоким пересечением текста.
    Возвращает id дубля или None.
    """
    if not card_text or len(card_text) < 100:
        return None

    card_words = _word_set(card_text)
    if not card_words:
        return None

    since = datetime.utcnow() - timedelta(hours=since_hours)
    with get_session() as s:
        candidates = (
            s.query(NewsCard)
            .filter(NewsCard.llm_enriched == True)  # noqa: E712
            .filter(NewsCard.created_at >= since)
            .filter(NewsCard.id != card_id)
            .filter(NewsCard.clean_text != None)  # noqa: E711
            .all()
        )
        for c in candidates:
            other_words = _word_set(c.clean_text or "")
            if not other_words:
                continue
            overlap = len(card_words & other_words) / max(len(card_words), len(other_words))
            if overlap >= overlap_threshold:
                logger.debug(
                    f"Early duplicate: card #{card_id} ~ #{c.id} ({overlap:.0%} overlap)"
                )
                return c.id
    return None
