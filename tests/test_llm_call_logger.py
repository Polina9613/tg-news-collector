"""Tests for llm/call_logger.py"""
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import LLMCallLog


@pytest.fixture
def mem_db():
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

    with patch("llm.call_logger.get_session", _gs):
        yield _gs


@pytest.fixture(autouse=True)
def clear_context():
    """Сбрасывает thread-local LLM-контекст до и после каждого теста."""
    from llm.call_logger import set_call_context
    set_call_context("unknown", None, None, None)
    yield
    set_call_context("unknown", None, None, None)


def test_log_llm_call_writes_to_db(mem_db):
    from llm.call_logger import log_llm_call, set_call_context

    set_call_context("test_method", news_card_id=42, context_note="unit test")
    log_llm_call(
        provider="test",
        model="test-model",
        prompt_chars=100,
        response_chars=50,
        duration_ms=1200,
        usage={"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50},
    )

    with mem_db() as s:
        logs = s.query(LLMCallLog).all()
        assert len(logs) == 1
        assert logs[0].method == "test_method"
        assert logs[0].news_card_id == 42
        assert logs[0].total_tokens == 50
        assert logs[0].success is True


def test_log_survives_missing_context(mem_db):
    from llm.call_logger import log_llm_call

    log_llm_call(
        provider="test", model="test-model",
        prompt_chars=10, response_chars=10, duration_ms=100,
    )

    with mem_db() as s:
        logs = s.query(LLMCallLog).all()
        assert len(logs) == 1
        assert logs[0].method == "unknown"


def test_llm_call_context_manager(mem_db):
    from llm.call_logger import get_call_context, llm_call_context, log_llm_call

    with llm_call_context("inside_ctx", news_card_id=99):
        ctx = get_call_context()
        assert ctx["method"] == "inside_ctx"
        assert ctx["news_card_id"] == 99
        log_llm_call(provider="t", model="m", prompt_chars=1, response_chars=1, duration_ms=1)

    ctx_after = get_call_context()
    assert ctx_after["method"] == "unknown"


def test_cache_hit_tokens_stored(mem_db):
    from llm.call_logger import log_llm_call, set_call_context

    set_call_context("check_relevance_and_classify")
    log_llm_call(
        provider="deepseek",
        model="deepseek-chat",
        prompt_chars=500,
        response_chars=80,
        duration_ms=800,
        usage={
            "prompt_tokens": 200,
            "completion_tokens": 50,
            "total_tokens": 250,
            "prompt_cache_hit_tokens": 180,
            "prompt_cache_miss_tokens": 20,
        },
    )

    with mem_db() as s:
        log = s.query(LLMCallLog).first()
        assert log is not None
        assert log.cache_hit_tokens == 180
        assert log.cache_miss_tokens == 20
        assert log.total_tokens == 250
