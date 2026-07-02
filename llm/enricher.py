import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import or_

from db.base import get_session
from db.models import NewsCard, Trend, TrendCase, get_period_label


@dataclass
class EnrichResult:
    total: int = 0
    relevant: int = 0
    irrelevant: int = 0
    news_only: int = 0
    cases_created: int = 0
    pending_trends: int = 0
    duplicates_marked: int = 0
    skipped_empty: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


def _prepare_text(card) -> str:
    """Обрезает длинные тексты — DeepSeek таймаутит на текстах > 2000 символов."""
    text = card.clean_text or ""
    if len(text) <= 1800:
        return text
    truncated = text[:1500]
    last_dot = truncated.rfind(". ")
    if last_dot > 800:
        truncated = truncated[:last_dot + 1]
    return truncated + "\n\n[текст обрезан]"


def _load_active_trends() -> list[dict]:
    """Загружает список активных трендов из БД для передачи в LLM."""
    with get_session() as s:
        trends = s.query(Trend).filter(Trend.status == "active").all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description or "",
                "category": t.category or "",
            }
            for t in trends
        ]


def _create_pending_trend(name: str, description: str, case_id: int) -> int | None:
    """Создаёт новый тренд со статусом pending для последующей модерации."""
    import re as _re

    try:
        from transliterate import translit
        latin = translit(name, "ru", reversed=True)
    except Exception:
        latin = name
    slug = _re.sub(r"[^a-z0-9]+", "-", latin.lower().strip()).strip("-")[:80]
    if not slug:
        slug = f"pending-{int(time.time())}"

    with get_session() as s:
        existing = s.query(Trend).filter(
            (Trend.name == name) | (Trend.slug == slug)
        ).first()
        if existing:
            return existing.id
        try:
            trend = Trend(
                name=name,
                slug=slug,
                description=description,
                status="pending",
                proposed_by_case_id=case_id,
            )
            s.add(trend)
            s.flush()
            return trend.id
        except Exception as e:
            logger.warning(f"Failed to create pending trend '{name}': {e}")
            return None


def _build_channel_context(card) -> str | None:
    """Формирует контекст канала для LLM-промптов, включая тематику из БД."""
    if not card.source_title:
        return None

    import json as _json

    from db.base import get_session
    from db.models import Source

    with get_session() as s:
        source = s.query(Source).filter(Source.title == card.source_title).first()
        if not source or not source.topics:
            return f"канал «{card.source_title}»"
        try:
            topics = _json.loads(source.topics)
            if isinstance(topics, list) and topics:
                return f"канал «{card.source_title}» (тематика: {', '.join(topics)})"
        except Exception:
            pass
    return f"канал «{card.source_title}»"


def _check_duplicate(case: dict, since_days: int = 5) -> int | None:
    """
    Проверяет — есть ли уже похожий кейс в БД за последние N дней.
    Похожий = та же компания + пересечение значимых слов в case_title > 50%.
    """
    company = case.get("company") or ""
    case_title = case.get("case_title") or ""
    if not company or not case_title:
        return None

    since = datetime.utcnow() - timedelta(days=since_days)
    case_words = {w.lower() for w in case_title.split() if len(w) >= 4}
    if not case_words:
        return None

    with get_session() as s:
        candidates = (
            s.query(TrendCase)
            .filter(TrendCase.company == company)
            .filter(TrendCase.created_at >= since)
            .filter(TrendCase.is_duplicate == False)  # noqa: E712
            .all()
        )
        for c in candidates:
            if not c.case_title:
                continue
            other_words = {w.lower() for w in c.case_title.split() if len(w) >= 4}
            if not other_words:
                continue
            overlap = len(case_words & other_words) / max(len(case_words), len(other_words))
            if overlap > 0.5:
                logger.debug(f"Duplicate detected: '{case_title}' ~ '{c.case_title}' ({overlap:.0%})")
                return c.id
    return None


def enrich_news_cards(
    provider,
    min_score: int = 25,
    limit: int = 30,
    reprocess: bool = False,
    fallback_provider=None,
) -> EnrichResult:
    """
    Многоступенчатое обогащение карточек:
    1. check_relevance_and_classify — релевантность + тип (1 вызов вместо 2)
    2. Для новостей: авто-резюме из clean_text (без LLM)
    3. Для кейсов: extract_cases + assign_trend
    """
    result = EnrichResult()

    def _llm_call_with_fallback(method_name: str, *args, **kwargs):
        """Вызывает метод провайдера, при ошибке пробует fallback."""
        try:
            return getattr(provider, method_name)(*args, **kwargs)
        except Exception as e:
            if fallback_provider:
                logger.warning(
                    f"Primary provider failed ({method_name}: {e}), trying fallback..."
                )
                return getattr(fallback_provider, method_name)(*args, **kwargs)
            raise

    with get_session() as session:
        query = session.query(NewsCard)
        if not reprocess:
            query = query.filter(NewsCard.llm_enriched == False)  # noqa: E712
        query = query.filter(NewsCard.relevance_score >= min_score)
        query = query.filter(
            or_(
                NewsCard.llm_retry_after == None,  # noqa: E711
                NewsCard.llm_retry_after <= datetime.utcnow(),
            )
        )
        query = query.order_by(NewsCard.relevance_score.desc())
        card_ids = [c.id for c in query.limit(limit).all()]

    result.total = len(card_ids)
    logger.info(f"Enrich: {result.total} cards to process (min_score={min_score})")

    active_trends = _load_active_trends()
    logger.info(f"Active trends in DB: {len(active_trends)}")

    for i, card_id in enumerate(card_ids, 1):
        try:
            with get_session() as session:
                card = session.get(NewsCard, card_id)
                if not card or not card.clean_text:
                    result.skipped_empty += 1
                    continue

                logger.info(f"[{i}/{result.total}] {(card.title or '?')[:60]}")

                channel_context = _build_channel_context(card)
                text = _prepare_text(card)

                # ── Ступень 1+2: релевантность и классификация (1 вызов) ──
                rc = _llm_call_with_fallback("check_relevance_and_classify", text, channel_context)
                relevant = rc["relevant"]
                card.llm_relevant = relevant

                if not relevant:
                    result.irrelevant += 1
                    logger.debug(f"  → irrelevant: {rc['relevance_reason']}")
                    card.llm_enriched = True
                    card.llm_enriched_at = datetime.utcnow()
                    continue

                result.relevant += 1
                post_type = rc.get("type", "news")
                logger.debug(f"  → {post_type}: {rc.get('classify_reason', '')}")

                # Авто-резюме из clean_text (без LLM) — используется в Excel
                if not card.summary:
                    card.summary = (card.clean_text or "")[:280].rsplit(" ", 1)[0] + "…"

                # ── Ступень 2: новость — готово ───────────────────────────
                if post_type == "news":
                    result.news_only += 1
                    card.llm_enriched = True
                    card.llm_enriched_at = datetime.utcnow()
                    logger.debug("  → news, auto-summary set")
                    continue

                # ── Ступень 3: кейс → извлечение + привязка к тренду ─────
                time.sleep(6)
                source_url = card.source_url or card.post_url
                cases_data = _llm_call_with_fallback("extract_cases", text, source_url, channel_context)
                logger.debug(f"  → extracted {len(cases_data)} case(s)")

                for case_data in cases_data:
                    time.sleep(5)

                    # Привязка к тренду
                    trend_decision = _llm_call_with_fallback("assign_trend", case_data, active_trends)
                    decision = trend_decision.get("decision", "none")
                    trend_id = None

                    if decision == "existing":
                        trend_id = trend_decision.get("trend_id")
                        logger.debug(f"  → trend: existing #{trend_id}")
                    elif decision == "new":
                        logger.debug(f"  → trend: NEW '{trend_decision.get('new_trend_name')}'")

                    # Проверка дублей
                    dup_of = _check_duplicate(case_data)
                    is_dup = dup_of is not None
                    if is_dup:
                        result.duplicates_marked += 1
                        logger.debug(f"  → duplicate of #{dup_of}")

                    # Создаём TrendCase
                    tc = TrendCase(
                        news_card_id=card.id,
                        trend_id=trend_id,
                        trend_name=None,
                        case_title=case_data.get("case_title"),
                        company=case_data.get("company"),
                        description=case_data.get("description"),
                        how_it_works=case_data.get("how_it_works"),
                        value=case_data.get("value"),
                        market=case_data.get("market"),
                        industry=case_data.get("industry"),
                        source_url=case_data.get("source_url"),
                        is_duplicate=is_dup,
                        duplicate_of_case_id=dup_of,
                        period_label=(
                            get_period_label(card.published_at) if card.published_at else None
                        ),
                    )
                    session.add(tc)
                    session.flush()
                    result.cases_created += 1

                    # Создаём pending тренд если LLM предложила новый
                    if decision == "new":
                        time.sleep(3)
                        new_trend_id = _create_pending_trend(
                            name=trend_decision.get("new_trend_name") or "",
                            description=trend_decision.get("new_trend_description") or "",
                            case_id=tc.id,
                        )
                        if new_trend_id:
                            tc.trend_id = new_trend_id
                            result.pending_trends += 1

                card.llm_enriched = True
                card.llm_enriched_at = datetime.utcnow()

        except Exception as e:
            error_str = str(e)
            result.errors += 1
            result.error_messages.append(f"card_id={card_id}: {e}")
            logger.error(f"Enrich error card_id={card_id}: {e}")

            is_timeout = "timed out" in error_str.lower() or "timeout" in error_str.lower()
            is_empty = "empty response" in error_str.lower() or "NoneType" in error_str
            is_rate_limit = "429" in error_str or "Too Many Requests" in error_str

            if is_timeout or is_empty or is_rate_limit:
                with get_session() as _s:
                    _card = _s.get(NewsCard, card_id)
                    if _card:
                        _card.llm_retry_after = datetime.utcnow() + timedelta(hours=2)
                        reason = "timeout" if is_timeout else ("empty" if is_empty else "rate_limit")
                        logger.warning(
                            f"card_id={card_id} sent to back of queue ({reason})"
                            f" — retry after 2h"
                        )

                if is_timeout or is_rate_limit:
                    logger.warning("Stopping current enrich cycle early")
                    break

        time.sleep(10)

    logger.info(
        f"Enrich done: relevant={result.relevant} irrelevant={result.irrelevant} "
        f"news_only={result.news_only} cases={result.cases_created} "
        f"pending_trends={result.pending_trends} duplicates={result.duplicates_marked} "
        f"errors={result.errors}"
    )
    return result
