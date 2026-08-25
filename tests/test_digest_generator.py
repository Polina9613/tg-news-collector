"""Tests: digest/generator._load_cases filtering logic."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import NewsCard, RawPost, Source, TrendCase


@pytest.fixture
def gen_db():
    """In-memory SQLite with get_session patched in digest.generator."""
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

    with patch("digest.generator.get_session", _get_session):
        yield _get_session


def _make_card_and_case(gs, suffix, relevance_score, importance_score, delta_days=2):
    """Creates Source + RawPost + NewsCard + TrendCase; returns (card_id, tc_id)."""
    now = datetime.utcnow()
    with gs() as s:
        src = Source(username=f"@ch{suffix}", title=f"Ch{suffix}", topics="[]", is_active=True)
        s.add(src)
        s.flush()

        post = RawPost(
            source_id=src.id,
            message_id=suffix,
            channel_username=f"@ch{suffix}",
            post_url=f"https://t.me/ch{suffix}/1",
            raw_text="text",
            text_hash=f"h{suffix}",
            published_at=now - timedelta(days=delta_days),
            has_media=False,
            is_forwarded=False,
        )
        s.add(post)
        s.flush()

        card = NewsCard(
            raw_post_id=post.id,
            title=f"T{suffix}",
            source_title=f"Ch{suffix}",
            post_url=f"https://t.me/ch{suffix}/1",
            published_at=now - timedelta(days=delta_days),
            clean_text="text",
            relevance_score=relevance_score,
            relevance_label="high",
        )
        s.add(card)
        s.flush()

        tc = TrendCase(
            news_card_id=card.id,
            case_title=f"Кейс{suffix}",
            company=f"Co{suffix}",
            importance_score=importance_score,
            is_duplicate=False,
            created_at=now - timedelta(days=delta_days),
        )
        s.add(tc)
        s.flush()
        return card.id, tc.id


def test_load_cases_filters_by_importance_score(gen_db):
    """Кейс с высоким importance_score но низким rule-based relevance_score
    должен попасть в дайджест. Кейс с низким importance_score — нет."""
    _make_card_and_case(gen_db, suffix=1, relevance_score=67, importance_score=85)
    _make_card_and_case(gen_db, suffix=2, relevance_score=100, importance_score=30)

    from digest.generator import _load_cases
    now = datetime.utcnow()
    cases = _load_cases(now - timedelta(days=7), now + timedelta(hours=1), 30)

    titles = [c["case_title"] for c in cases]
    assert "Кейс1" in titles
    assert "Кейс2" not in titles


def test_load_cases_includes_importance_score_in_result(gen_db):
    """Результат _load_cases содержит поле importance_score."""
    _make_card_and_case(gen_db, suffix=10, relevance_score=80, importance_score=75)

    from digest.generator import _load_cases
    now = datetime.utcnow()
    cases = _load_cases(now - timedelta(days=7), now + timedelta(hours=1), 30)

    assert len(cases) == 1
    assert cases[0]["importance_score"] == 75


def test_load_cases_null_importance_score_uses_default(gen_db):
    """Кейс без importance_score (NULL → дефолт 50) ниже порога 60 — не попадает."""
    _make_card_and_case(gen_db, suffix=20, relevance_score=95, importance_score=None)

    from digest.generator import _load_cases
    now = datetime.utcnow()
    cases = _load_cases(now - timedelta(days=7), now + timedelta(hours=1), 30)

    assert all(c["case_title"] != "Кейс20" for c in cases)
