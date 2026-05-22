from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from db.base import get_session
from db.models import NewsCard, RawPost
from processor.card_builder import build_news_card


@dataclass
class ProcessResult:
    total: int
    created: int
    skipped_duplicate: int
    skipped_empty: int
    errors: int


def process_raw_posts(since: datetime | None = None) -> ProcessResult:
    with get_session() as session:
        stmt = (
            select(RawPost.id)
            .outerjoin(NewsCard, RawPost.id == NewsCard.raw_post_id)
            .where(NewsCard.id.is_(None))
        )
        if since is not None:
            stmt = stmt.where(RawPost.published_at >= since)
        post_ids: list[int] = list(session.execute(stmt).scalars())

    result = ProcessResult(
        total=len(post_ids),
        created=0,
        skipped_duplicate=0,
        skipped_empty=0,
        errors=0,
    )
    logger.info(f"Processing {result.total} unprocessed posts")

    for i, post_id in enumerate(post_ids, 1):
        if i % 50 == 0:
            logger.info(f"Progress: {i}/{result.total}")
        try:
            with get_session() as session:
                post = session.get(RawPost, post_id)
                if post is None:
                    result.errors += 1
                    continue
                existing = session.execute(
                    select(NewsCard).where(NewsCard.raw_post_id == post_id)
                ).scalar_one_or_none()
                if existing is not None:
                    result.skipped_duplicate += 1
                    continue
                card = build_news_card(post, session)
                if card is None:
                    result.skipped_empty += 1
                    continue
                session.add(card)
                result.created += 1
        except Exception as e:
            logger.error(f"Error processing post {post_id}: {e}")
            result.errors += 1

    logger.info(
        f"Done: created={result.created} empty={result.skipped_empty}"
        f" dupes={result.skipped_duplicate} errors={result.errors}"
    )
    return result


def reprocess_all_cards() -> ProcessResult:
    """Удаляет все NewsCard и пересоздаёт их из RawPost."""
    from db.models import TrendCase  # local import to avoid circular
    with get_session() as session:
        session.query(TrendCase).delete()
        session.query(NewsCard).delete()
        logger.info("All NewsCards and TrendCases deleted, reprocessing...")
    return process_raw_posts()
