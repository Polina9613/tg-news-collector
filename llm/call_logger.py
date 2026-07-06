"""Логгирование LLM-вызовов в БД."""
import threading
from contextlib import contextmanager
from datetime import datetime

from loguru import logger

from db.base import get_session
from db.models import LLMCallLog

_context = threading.local()


def set_call_context(
    method: str,
    news_card_id: int | None = None,
    trend_case_id: int | None = None,
    context_note: str | None = None,
) -> None:
    """Устанавливает контекст перед вызовом LLM. Читается в _call провайдера."""
    _context.method = method
    _context.news_card_id = news_card_id
    _context.trend_case_id = trend_case_id
    _context.context_note = context_note


def get_call_context() -> dict:
    return {
        "method": getattr(_context, "method", "unknown"),
        "news_card_id": getattr(_context, "news_card_id", None),
        "trend_case_id": getattr(_context, "trend_case_id", None),
        "context_note": getattr(_context, "context_note", None),
    }


def log_llm_call(
    provider: str,
    model: str,
    prompt_chars: int,
    response_chars: int,
    duration_ms: int,
    usage: dict | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> None:
    """Записывает вызов в БД. Никогда не бросает исключения — только логирует."""
    ctx = get_call_context()
    usage = usage or {}

    try:
        with get_session() as s:
            entry = LLMCallLog(
                called_at=datetime.utcnow(),
                provider=provider,
                model=model,
                method=ctx["method"],
                news_card_id=ctx["news_card_id"],
                trend_case_id=ctx["trend_case_id"],
                context_note=ctx["context_note"],
                prompt_chars=prompt_chars,
                response_chars=response_chars,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                cache_hit_tokens=usage.get("prompt_cache_hit_tokens"),
                cache_miss_tokens=usage.get("prompt_cache_miss_tokens"),
                duration_ms=duration_ms,
                success=success,
                error_message=error_message,
            )
            s.add(entry)
    except Exception as e:
        logger.warning(f"Failed to log LLM call: {e}")


@contextmanager
def llm_call_context(
    method: str,
    news_card_id: int | None = None,
    trend_case_id: int | None = None,
    context_note: str | None = None,
):
    """Контекстный менеджер для установки метаданных перед LLM-вызовом."""
    set_call_context(method, news_card_id, trend_case_id, context_note)
    try:
        yield
    finally:
        set_call_context("unknown", None, None, None)
