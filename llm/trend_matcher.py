import json
import re
import time

from loguru import logger
from sqlalchemy.exc import IntegrityError

from db.base import get_session
from db.models import Trend


def _make_slug(name: str) -> str:
    """Транслитерирует кириллицу и формирует slug. Fallback — timestamp."""
    try:
        from transliterate import translit
        latin = translit(name, "ru", reversed=True)
    except Exception:
        latin = name
    slug = re.sub(r"[^a-z0-9]+", "-", latin.lower().strip()).strip("-")[:80]
    if not slug:
        slug = f"trend-{int(time.time())}"
    return slug


def get_or_create_trend(provider, trend_name: str, description: str) -> int | None:
    """
    Находит существующий тренд по смыслу или создаёт новый.
    Возвращает trend_id или None при ошибке.
    """
    if not trend_name:
        return None

    try:
        with get_session() as session:
            existing_trends = session.query(Trend).all()
            existing = [{"id": t.id, "name": t.name} for t in existing_trends]

        if not existing:
            return _create_trend(provider, trend_name, description)

        time.sleep(4)  # пауза перед LLM-вызовом _match_trend
        matched_id = _match_trend(provider, trend_name, description, existing)

        if matched_id:
            logger.debug(f"Trend matched: '{trend_name}' → id={matched_id}")
            return matched_id

        logger.debug(f"New trend created: '{trend_name}'")
        time.sleep(4)  # пауза перед LLM-вызовом внутри _create_trend
        return _create_trend(provider, trend_name, description)

    except Exception as e:
        logger.error(f"trend_matcher error for '{trend_name}': {e}")
        return None


def _match_trend(provider, name: str, description: str, existing: list[dict]) -> int | None:
    """LLM определяет: относится ли кейс к одному из существующих трендов."""
    system = "Ты — аналитик финтех-рынка. Отвечай строго JSON."
    existing_list = "\n".join(f"- id={t['id']}: {t['name']}" for t in existing)
    user = f"""Определи: относится ли новый кейс к одному из существующих трендов?

Новый кейс:
Название тренда: {name}
Описание: {description[:300]}

Существующие тренды:
{existing_list}

Если кейс относится к существующему тренду — верни его id.
Если ни один не подходит — верни null.

Ответ строго JSON: {{"trend_id": 3}} или {{"trend_id": null}}"""

    raw = provider._call(system, user)
    try:
        match = re.search(r'\{.*?\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}
        val = data.get("trend_id")
        return int(val) if val is not None else None
    except Exception as e:
        logger.warning(f"trend match parse error: {e}")
        return None


def _create_trend(provider, name: str, description: str) -> int | None:
    """Создаёт новый тренд в БД, генерирует описание через LLM."""
    slug = _make_slug(name)

    system = "Ты — аналитик финтех-рынка."
    user = f"""Напиши краткое описание тренда «{name}» (2-3 предложения).
Пиши для аналитиков финтех-рынка. Что это за тренд, почему важен.
Только текст, без заголовков."""

    trend_description = provider._call(system, user)

    try:
        with get_session() as session:
            existing = session.query(Trend).filter_by(name=name).first()
            if existing:
                return existing.id

            trend = Trend(
                name=name,
                slug=slug,
                description=trend_description,
            )
            session.add(trend)
            session.flush()
            return trend.id
    except IntegrityError:
        logger.warning(f"Trend '{name}' already exists (race condition), fetching existing")
        with get_session() as session:
            existing = session.query(Trend).filter(
                (Trend.name == name) | (Trend.slug == slug)
            ).first()
            return existing.id if existing else None
