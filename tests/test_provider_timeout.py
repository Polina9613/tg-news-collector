"""Tests: per-call timeout override in LLM providers."""
from unittest.mock import MagicMock, patch


def _make_mock_response(content: str = "ok") -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {},
    }
    r.raise_for_status = MagicMock()
    return r


def test_deepseek_uses_custom_timeout():
    from llm.deepseek_provider import DeepSeekProvider

    provider = DeepSeekProvider(api_key="test", model="test-model", timeout=60)
    with patch("httpx.post", return_value=_make_mock_response()) as mock_post:
        provider._call("sys", "user", timeout=180)
    assert mock_post.call_args.kwargs.get("timeout") == 180


def test_deepseek_uses_default_timeout_when_not_specified():
    from llm.deepseek_provider import DeepSeekProvider

    provider = DeepSeekProvider(api_key="test", model="test-model", timeout=45)
    with patch("httpx.post", return_value=_make_mock_response()) as mock_post:
        provider._call("sys", "user")
    assert mock_post.call_args.kwargs.get("timeout") == 45


def test_groq_uses_custom_timeout():
    from llm.groq_provider import GroqProvider

    provider = GroqProvider(api_key="test", model="test-model", timeout=60)
    with patch("httpx.post", return_value=_make_mock_response()) as mock_post:
        provider._call("sys", "user", timeout=180)
    assert mock_post.call_args.kwargs.get("timeout") == 180


def test_groq_uses_default_timeout_when_not_specified():
    from llm.groq_provider import GroqProvider

    provider = GroqProvider(api_key="test", model="test-model", timeout=45)
    with patch("httpx.post", return_value=_make_mock_response()) as mock_post:
        provider._call("sys", "user")
    assert mock_post.call_args.kwargs.get("timeout") == 45


def test_yandex_uses_custom_timeout():
    from llm.yandex_provider import YandexProvider

    provider = YandexProvider(api_key="test", folder_id="folder", timeout=60)
    with patch("httpx.post", return_value=_make_mock_response()) as mock_post:
        provider._call("sys", "user", timeout=180)
    assert mock_post.call_args.kwargs.get("timeout") == 180


def test_yandex_uses_default_timeout_when_not_specified():
    from llm.yandex_provider import YandexProvider

    provider = YandexProvider(api_key="test", folder_id="folder", timeout=45)
    with patch("httpx.post", return_value=_make_mock_response()) as mock_post:
        provider._call("sys", "user")
    assert mock_post.call_args.kwargs.get("timeout") == 45


# ── reasoning_effort tests ────────────────────────────────────────────────────

def test_deepseek_passes_reasoning_effort():
    """reasoning_effort="low" попадает в тело запроса."""
    from llm.deepseek_provider import DeepSeekProvider

    provider = DeepSeekProvider(api_key="test", model="deepseek-v4-flash", timeout=60)
    with patch("httpx.post", return_value=_make_mock_response()) as mock_post:
        provider._call("system", "user", reasoning_effort="low")
    body = mock_post.call_args.kwargs.get("json", {})
    assert body.get("reasoning_effort") == "low"


def test_deepseek_omits_reasoning_effort_when_not_specified():
    """Без reasoning_effort ключ не включается в payload."""
    from llm.deepseek_provider import DeepSeekProvider

    provider = DeepSeekProvider(api_key="test", model="deepseek-v4-flash", timeout=60)
    with patch("httpx.post", return_value=_make_mock_response()) as mock_post:
        provider._call("system", "user")
    body = mock_post.call_args.kwargs.get("json", {})
    assert "reasoning_effort" not in body


def test_groq_ignores_reasoning_effort_param():
    """Groq-провайдер принимает reasoning_effort и не падает."""
    from llm.groq_provider import GroqProvider

    provider = GroqProvider(api_key="test", model="llama-3.3-70b-versatile", timeout=60)
    with patch("httpx.post", return_value=_make_mock_response()):
        result = provider._call("system", "user", reasoning_effort="low")
    assert result == "ok"


# ── importance_score prompt tests ─────────────────────────────────────────────

def test_extract_cases_importance_reflects_fintech_relevance():
    """_EXTRACT_CASES_SYSTEM содержит ориентацию importance_score на банковского аналитика."""
    from llm.deepseek_provider import _EXTRACT_CASES_SYSTEM as ds_system
    from llm.groq_provider import _EXTRACT_CASES_SYSTEM as groq_system
    from llm.yandex_provider import _EXTRACT_CASES_SYSTEM as ya_system

    for prompt in (ds_system, groq_system, ya_system):
        low = prompt.lower()
        assert "аналитик" in low, "должно упоминаться 'аналитик'"
        assert "банк" in low, "должно упоминаться 'банк'"
        assert "платеж" in low or "платёж" in low, "должно упоминаться 'платёж'"
        assert "importance_score" in low, "должна быть секция importance_score"


# ── batch_score_importance tests ──────────────────────────────────────────────

def test_batch_score_importance_returns_scores():
    from unittest.mock import MagicMock
    from llm.deepseek_provider import DeepSeekProvider

    provider = DeepSeekProvider(api_key="test", model="deepseek-chat", timeout=60)
    provider._call = MagicMock(return_value='{"scores": [90, 45, 70]}')

    cases = [
        {"case_title": "A", "company": "Сбер", "description": "desc"},
        {"case_title": "B", "company": "X", "description": "desc"},
        {"case_title": "C", "company": "Y", "description": "desc"},
    ]
    result = provider.batch_score_importance(cases)
    assert result == [90, 45, 70]


def test_batch_score_importance_handles_mismatched_length():
    from unittest.mock import MagicMock
    from llm.deepseek_provider import DeepSeekProvider

    provider = DeepSeekProvider(api_key="test", model="deepseek-chat", timeout=60)
    provider._call = MagicMock(return_value='{"scores": [90]}')

    cases = [
        {"case_title": "A", "company": "X", "description": ""},
        {"case_title": "B", "company": "Y", "description": ""},
        {"case_title": "C", "company": "Z", "description": ""},
    ]
    result = provider.batch_score_importance(cases)
    assert len(result) == 3
    assert result[0] == 90
    assert result[1] == 50


def test_batch_score_importance_empty_list():
    from llm.deepseek_provider import DeepSeekProvider

    provider = DeepSeekProvider(api_key="test", model="deepseek-chat", timeout=60)
    result = provider.batch_score_importance([])
    assert result == []
