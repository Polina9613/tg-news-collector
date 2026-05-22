import time
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

from db.base import get_session
from db.models import NewsCard, TrendCase, get_period_label
from llm.trend_matcher import get_or_create_trend


@dataclass
class EnrichResult:
    total: int = 0
    relevant: int = 0
    irrelevant: int = 0
    cases_created: int = 0
    skipped_empty: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)


def enrich_news_cards(
    provider,
    min_score: int = 20,
    limit: int = 30,
    reprocess: bool = False,
) -> EnrichResult:
    result = EnrichResult()

    with get_session() as session:
        query = session.query(NewsCard)
        if not reprocess:
            query = query.filter(NewsCard.llm_enriched == False)  # noqa: E712
        query = query.filter(NewsCard.relevance_score >= min_score)
        query = query.order_by(NewsCard.relevance_score.desc())
        card_ids = [c.id for c in query.limit(limit).all()]

    result.total = len(card_ids)
    logger.info(f"Enrich: {result.total} cards queued (min_score={min_score})")

    for i, card_id in enumerate(card_ids, 1):
        try:
            with get_session() as session:
                card = session.get(NewsCard, card_id)
                if not card or not card.clean_text:
                    result.skipped_empty += 1
                    continue

                logger.info(f"[{i}/{result.total}] {card.title[:60]}")

                relevant, reason = provider.check_relevance(card.clean_text)
                card.llm_relevant = relevant

                if not relevant:
                    result.irrelevant += 1
                    logger.debug(f"  → irrelevant: {reason}")
                    card.llm_enriched = True
                    card.llm_enriched_at = datetime.utcnow()
                    continue

                result.relevant += 1

                card.summary = provider.generate_summary(card.clean_text)
                logger.debug(f"  → summary: {card.summary[:80]}")

                source_url = card.source_url or card.post_url
                cases_data = provider.extract_cases(card.clean_text, source_url)

                for case_data in cases_data:
                    time.sleep(6)  # rate limit before trend_matcher LLM call
                    trend_id = get_or_create_trend(
                        provider,
                        trend_name=case_data.get("trend_name", ""),
                        description=case_data.get("description", ""),
                    )
                    session.add(TrendCase(
                        news_card_id=card.id,
                        trend_id=trend_id,
                        trend_name=case_data.get("trend_name"),
                        case_title=case_data.get("case_title"),
                        company=case_data.get("company"),
                        description=case_data.get("description"),
                        how_it_works=case_data.get("how_it_works"),
                        value=case_data.get("value"),
                        source_url=case_data.get("source_url"),
                        market=case_data.get("market"),
                        period_label=get_period_label(card.published_at) if card.published_at else None,
                    ))
                    result.cases_created += 1

                logger.debug(f"  → {len(cases_data)} cases created")
                card.llm_enriched = True
                card.llm_enriched_at = datetime.utcnow()

        except Exception as e:
            result.errors += 1
            result.error_messages.append(f"card_id={card_id}: {e}")
            logger.error(f"Enrich error card_id={card_id}: {e}")
        finally:
            time.sleep(6)  # 6 сек между карточками = ~10 карточек/мин

    logger.info(
        f"Enrich done: relevant={result.relevant} irrelevant={result.irrelevant} "
        f"cases={result.cases_created} errors={result.errors}"
    )
    return result
