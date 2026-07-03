"""Tests for research module."""
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import Trend, TrendCase


def test_resolve_query_to_trends():
    from research.llm_research import resolve_query_to_trends

    provider = MagicMock()
    provider._call.return_value = '{"trend_ids": [1, 4]}'
    trends = [
        {"id": 1, "name": "Биометрические платежи"},
        {"id": 4, "name": "Физ. инфраструктура"},
    ]
    result = resolve_query_to_trends(provider, "офлайн платежи", trends)
    assert result == [1, 4]


def test_resolve_query_empty_on_no_match():
    from research.llm_research import resolve_query_to_trends

    provider = MagicMock()
    provider._call.return_value = '{"trend_ids": []}'
    result = resolve_query_to_trends(provider, "погода в Москве", [])
    assert result == []


def test_synthesis_returns_four_sections():
    from research.llm_research import generate_research_synthesis

    provider = MagicMock()
    provider._call.return_value = (
        '{"overview": "О1", "technology": "Т1", "players": "И1", "conclusions": "В1"}'
    )
    result = generate_research_synthesis(provider, "тест", [])
    assert result["overview"] == "О1"
    assert result["technology"] == "Т1"
    assert result["players"] == "И1"
    assert result["conclusions"] == "В1"


def test_research_ready_trends_sql_only():
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
        trend = Trend(name="Тест-тренд", slug="test-trigger", status="active")
        s.add(trend)
        s.flush()
        for i in range(16):
            s.add(TrendCase(
                trend_id=trend.id,
                case_title=f"Кейс {i}",
                company="X",
                created_at=datetime.utcnow(),
                is_duplicate=False,
            ))

    with patch("research.trigger.get_session", _gs):
        from research.trigger import check_research_ready_trends
        ready = check_research_ready_trends(days=30, min_cases=15)

    assert len(ready) == 1
    assert ready[0]["count"] == 16
