"""Tests for processor/early_dedup.py"""
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import NewsCard, RawPost, Source


@pytest.fixture
def db_with_cards():
    """In-memory SQLite with a pre-enriched card for dedup testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    _Session = sessionmaker(engine, autocommit=False, autoflush=False)

    @contextmanager
    def _gs():
        s = _Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    with _gs() as s:
        src = Source(username="@testchan", title="Test Channel", topics="[]", is_active=True)
        s.add(src)
        s.flush()
        post = RawPost(
            source_id=src.id,
            message_id=1,
            channel_username="@testchan",
            post_url="https://t.me/testchan/1",
            published_at=datetime.utcnow(),
        )
        s.add(post)
        s.flush()
        original = NewsCard(
            raw_post_id=post.id,
            title="Face Pay запуск",
            clean_text=(
                "Банк запустил Face Pay. Клиенты могут снимать наличные "
                "через биометрию лица без карты в банкоматах. "
                "Технология уже доступна."
            ),
            source_title="Test Channel",
            published_at=datetime.utcnow(),
            relevance_score=80,
            relevance_label="high",
            post_url="https://t.me/testchan/1",
            llm_enriched=True,
        )
        s.add(original)

    with patch("processor.early_dedup.get_session", _gs):
        yield


def test_finds_similar_duplicate(db_with_cards):
    from processor.early_dedup import find_early_duplicate

    similar_text = (
        "Банк запустил Face Pay в банкоматах. Теперь клиенты могут снимать "
        "наличные через биометрию лица без карты. Новая технология уже доступна."
    )
    dup_id = find_early_duplicate(similar_text, card_id=999)
    assert dup_id is not None


def test_no_duplicate_for_different_topic(db_with_cards):
    from processor.early_dedup import find_early_duplicate

    different_text = (
        "Центральный банк России повысил ключевую ставку до двадцати одного "
        "процента годовых. Решение принято на заседании совета директоров."
    )
    dup_id = find_early_duplicate(different_text, card_id=999)
    assert dup_id is None


def test_skips_short_text(db_with_cards):
    from processor.early_dedup import find_early_duplicate

    dup_id = find_early_duplicate("Короткий текст", card_id=999)
    assert dup_id is None
