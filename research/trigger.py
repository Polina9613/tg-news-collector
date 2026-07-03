"""Проверка каких трендов накопили достаточно кейсов для research. Без LLM."""
from datetime import datetime, timedelta

from sqlalchemy import func

from db.base import get_session
from db.models import Trend, TrendCase


def check_research_ready_trends(days: int = 30, min_cases: int = 15) -> list[dict]:
    """Возвращает тренды с >= min_cases кейсов за последние days дней."""
    since = datetime.utcnow() - timedelta(days=days)
    with get_session() as s:
        results = (
            s.query(Trend.id, Trend.name, func.count(TrendCase.id).label("cnt"))
            .join(TrendCase, TrendCase.trend_id == Trend.id)
            .filter(TrendCase.created_at >= since)
            .filter(TrendCase.is_duplicate == False)  # noqa: E712
            .group_by(Trend.id)
            .having(func.count(TrendCase.id) >= min_cases)
            .order_by(func.count(TrendCase.id).desc())
            .all()
        )
    return [{"id": r.id, "name": r.name, "count": r.cnt} for r in results]
