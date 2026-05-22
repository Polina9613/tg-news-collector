from loguru import logger
from sqlalchemy import func, select, text

from db.base import Base, engine, get_session
from db.models import NewsCard, RawPost, Source, Trend, TrendCase  # noqa: F401 — registers all models with Base


def migrate_add_url_fields() -> None:
    """Добавляет поля ссылок в существующую БД если их нет."""
    with engine.connect() as conn:
        existing_raw = [row[1] for row in conn.execute(text("PRAGMA table_info(raw_posts)"))]
        existing_news = [row[1] for row in conn.execute(text("PRAGMA table_info(news_cards)"))]
        if "extracted_urls" not in existing_raw:
            conn.execute(text("ALTER TABLE raw_posts ADD COLUMN extracted_urls TEXT"))
            conn.commit()
            logger.info("Migration: added extracted_urls to raw_posts")
        if "source_url" not in existing_news:
            conn.execute(text("ALTER TABLE news_cards ADD COLUMN source_url TEXT"))
            conn.commit()
            logger.info("Migration: added source_url to news_cards")


def migrate_add_llm_fields() -> None:
    with engine.connect() as conn:
        existing = [r[1] for r in conn.execute(text("PRAGMA table_info(news_cards)"))]
        for col, definition in [
            ("summary", "TEXT"),
            ("llm_relevant", "BOOLEAN"),
            ("llm_enriched", "BOOLEAN DEFAULT 0"),
            ("llm_enriched_at", "DATETIME"),
        ]:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE news_cards ADD COLUMN {col} {definition}"))
                conn.commit()
                logger.info(f"Migration: added {col} to news_cards")
    Base.metadata.create_all(engine)
    logger.info("Migration: trend_cases table ready")


def migrate_add_trends() -> None:
    """Создаёт таблицу trends и добавляет поля в trend_cases."""
    Base.metadata.create_all(engine)  # создаст trends если нет
    with engine.connect() as conn:
        existing = [r[1] for r in conn.execute(text("PRAGMA table_info(trend_cases)"))]
        for col, definition in [
            ("trend_id", "INTEGER REFERENCES trends(id)"),
            ("period_label", "TEXT"),
        ]:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE trend_cases ADD COLUMN {col} {definition}"))
                conn.commit()
                logger.info(f"Migration: added {col} to trend_cases")


def init_db() -> None:
    Base.metadata.create_all(engine)
    logger.info("Database initialized: tables created (or already exist)")
    migrate_add_url_fields()
    migrate_add_llm_fields()
    migrate_add_trends()


def get_db_stats() -> dict:
    with get_session() as session:
        sources = session.scalar(select(func.count()).select_from(Source)) or 0
        raw_posts = session.scalar(select(func.count()).select_from(RawPost)) or 0
        news_cards = session.scalar(select(func.count()).select_from(NewsCard)) or 0
        by_status_rows = session.execute(
            select(NewsCard.review_status, func.count()).group_by(NewsCard.review_status)
        ).all()
        by_status = {row[0]: row[1] for row in by_status_rows}
    return {
        "sources": sources,
        "raw_posts": raw_posts,
        "news_cards": news_cards,
        "by_status": by_status,
    }
