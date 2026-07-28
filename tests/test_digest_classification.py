"""Tests: 'digest' post type bypasses extract_cases in enricher pipeline."""
from contextlib import contextmanager, ExitStack
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import NewsCard, RawPost, Source, TrendCase


@pytest.fixture
def enrich_db():
    """In-memory SQLite with get_session patched in enricher and related modules."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    _Session = sessionmaker(engine, autocommit=False, autoflush=False)

    @contextmanager
    def _get_session():
        s = _Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    targets = [
        "db.base.get_session",
        "llm.enricher.get_session",
        "processor.early_dedup.get_session",
    ]
    with ExitStack() as stack:
        for t in targets:
            stack.enter_context(patch(t, _get_session))
        yield _get_session

    engine.dispose()


_card_counter = 0


def _add_card(gs, title, text, score=70) -> int:
    global _card_counter
    _card_counter += 1
    idx = _card_counter
    with gs() as s:
        src = Source(username=f"@test{idx}", title=f"Test {idx}", topics="[]", is_active=True)
        s.add(src)
        s.flush()
        post = RawPost(
            source_id=src.id,
            message_id=idx,
            channel_username=f"@test{idx}",
            post_url=f"https://t.me/test/{idx}",
            published_at=datetime.utcnow(),
            has_media=False,
            is_forwarded=False,
        )
        s.add(post)
        s.flush()
        card = NewsCard(
            raw_post_id=post.id,
            title=title,
            clean_text=text,
            source_title=f"Test {idx}",
            post_url=f"https://t.me/test/{idx}",
            published_at=datetime.utcnow(),
            relevance_score=score,
            relevance_label="high",
            llm_enriched=False,
        )
        s.add(card)
        s.flush()
        return card.id


def test_digest_type_post_does_not_create_case(enrich_db):
    """Пост типа 'digest' (обзор нескольких систем) не создаёт TrendCase."""
    gs = enrich_db
    card_id = _add_card(
        gs,
        "Обзор ИИ-агентов",
        "Обзор систем класса Full Scaffolding: Darwin Gödel Machine, AlphaEvolve, Gödel Agent.",
    )

    mock_provider = MagicMock()
    mock_provider.check_relevance_and_classify.return_value = {
        "relevant": True,
        "relevance_reason": "про ИИ-агентов",
        "type": "digest",
        "case_count": 0,
    }

    from llm.enricher import enrich_news_cards

    with patch("llm.enricher.should_skip_llm", return_value=(False, "")), \
         patch("llm.enricher.find_early_duplicate", return_value=None), \
         patch("llm.enricher._load_active_trends", return_value=[]), \
         patch("llm.enricher._build_channel_context", return_value=None):
        result = enrich_news_cards(mock_provider, min_score=0, limit=10)

    assert result.digest_only == 1
    assert result.cases_created == 0
    mock_provider.extract_cases.assert_not_called()

    with gs() as s:
        cases = s.query(TrendCase).filter_by(news_card_id=card_id).all()
    assert len(cases) == 0


def test_case_type_still_creates_case(enrich_db):
    """Обычный кейс с одной компанией по-прежнему создаёт TrendCase."""
    gs = enrich_db
    _add_card(gs, "Сбер запустил Face Pay", "Сбербанк запустил Face Pay в 500 банкоматах.", score=80)

    mock_provider = MagicMock()
    mock_provider.check_relevance_and_classify.return_value = {
        "relevant": True,
        "relevance_reason": "финтех кейс",
        "type": "case",
        "case_count": 1,
    }
    mock_provider.extract_cases.return_value = [{
        "case_title": "Сбер запустил Face Pay",
        "company": "Сбер",
        "description": "Face Pay в банкоматах",
        "how_it_works": None,
        "value": "Удобство",
        "market": "Россия",
        "industry": "Финтех / банки",
        "source_url": "https://t.me/test_case/1",
    }]
    mock_provider.assign_trend.return_value = {
        "decision": "none",
        "trend_id": None,
        "new_trend_name": None,
        "new_trend_description": None,
        "reasoning": "единичный кейс",
    }

    from llm.enricher import enrich_news_cards

    with patch("llm.enricher.should_skip_llm", return_value=(False, "")), \
         patch("llm.enricher.find_early_duplicate", return_value=None), \
         patch("llm.enricher._load_active_trends", return_value=[]), \
         patch("llm.enricher._build_channel_context", return_value=None), \
         patch("time.sleep"):
        result = enrich_news_cards(mock_provider, min_score=0, limit=10)

    assert result.cases_created == 1
    assert result.digest_only == 0
    mock_provider.extract_cases.assert_called_once()


def test_digest_only_counter_accumulates(enrich_db):
    """digest_only считается для каждого digest-поста."""
    gs = enrich_db
    for i in range(3):
        _add_card(gs, f"Обзор #{i}", f"Примеры систем А, Б, В в обзоре {i}.")

    mock_provider = MagicMock()
    mock_provider.check_relevance_and_classify.return_value = {
        "relevant": True, "relevance_reason": "обзор", "type": "digest", "case_count": 0,
    }

    from llm.enricher import enrich_news_cards

    with patch("llm.enricher.should_skip_llm", return_value=(False, "")), \
         patch("llm.enricher.find_early_duplicate", return_value=None), \
         patch("llm.enricher._load_active_trends", return_value=[]), \
         patch("llm.enricher._build_channel_context", return_value=None):
        result = enrich_news_cards(mock_provider, min_score=0, limit=10)

    assert result.digest_only == 3
    assert result.cases_created == 0
