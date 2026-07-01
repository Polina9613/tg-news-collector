"""Тесты DeepSeek провайдера."""
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from llm.deepseek_provider import DEEPSEEK_API_URL, DeepSeekProvider


def _make_response(content: str):
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }
    mock.raise_for_status = MagicMock()
    return mock


@pytest.fixture
def provider():
    return DeepSeekProvider(api_key="test_key", model="deepseek-chat", timeout=10)


def test_correct_endpoint(provider):
    with patch("llm.deepseek_provider.httpx.post", return_value=_make_response("ok")) as mock_post:
        provider._call("system", "user")
    url = mock_post.call_args.args[0]
    assert "artemox.com" in url
    assert url == DEEPSEEK_API_URL


def test_bearer_auth(provider):
    with patch("llm.deepseek_provider.httpx.post", return_value=_make_response("ok")) as mock_post:
        provider._call("system", "user")
    headers = mock_post.call_args.kwargs.get("headers", {})
    assert headers.get("Authorization") == "Bearer test_key"


def test_model_name(provider):
    with patch("llm.deepseek_provider.httpx.post", return_value=_make_response("ok")) as mock_post:
        provider._call("system", "user")
    body = mock_post.call_args.kwargs.get("json", {})
    assert body.get("model") == "deepseek-chat"


def test_check_relevance_true(provider):
    with patch.object(provider, "_call", return_value='{"relevant": true, "reason": "финтех"}'):
        rel, reason = provider.check_relevance("тест")
    assert rel is True
    assert reason == "финтех"


def test_check_relevance_false(provider):
    with patch.object(provider, "_call", return_value='{"relevant": false, "reason": "не финтех"}'):
        rel, _ = provider.check_relevance("тест")
    assert rel is False


def test_classify_post(provider):
    with patch.object(provider, "_call", return_value='{"type": "case", "case_count": 1, "reason": "ok"}'):
        result = provider.classify_post("тест")
    assert result["type"] == "case"
    assert result["case_count"] == 1


def test_generate_summary(provider):
    with patch.object(provider, "_call", return_value="Краткое резюме новости."):
        summary = provider.generate_summary("тест")
    assert summary == "Краткое резюме новости."


def test_extract_cases_with_source_url(provider):
    raw = json.dumps([{
        "case_title": "Сбер запустил Face Pay",
        "company": "Сбер",
        "description": "desc",
        "how_it_works": None,
        "value": "v",
        "market": "Россия",
        "industry": "Финтех / банки",
    }])
    with patch.object(provider, "_call", return_value=raw):
        cases = provider.extract_cases("тест", "https://t.me/sber/1")
    assert len(cases) == 1
    assert cases[0]["source_url"] == "https://t.me/sber/1"
    assert cases[0]["company"] == "Сбер"


def test_extract_cases_malformed_returns_empty(provider):
    with patch.object(provider, "_call", return_value="not json"):
        cases = provider.extract_cases("тест", None)
    assert cases == []


def test_assign_trend_existing(provider):
    raw = json.dumps({
        "decision": "existing", "trend_id": 5,
        "new_trend_name": None, "new_trend_description": None,
        "reasoning": "подходит",
    })
    with patch.object(provider, "_call", return_value=raw):
        result = provider.assign_trend({"case_title": "тест"}, [])
    assert result["decision"] == "existing"
    assert result["trend_id"] == 5


def test_retry_on_429(provider):
    rate_resp = MagicMock()
    rate_resp.status_code = 429
    rate_resp.text = "rate limit"
    err = httpx.HTTPStatusError("429", request=MagicMock(), response=rate_resp)
    rate_resp.raise_for_status.side_effect = err

    ok_resp = _make_response("result")

    with patch("llm.deepseek_provider.httpx.post", side_effect=[rate_resp, ok_resp]), \
         patch("llm.deepseek_provider.time.sleep"):
        result = provider._call("sys", "usr")
    assert result == "result"


def test_retry_on_timeout(provider):
    ok_resp = _make_response("ok")
    with patch("llm.deepseek_provider.httpx.post",
               side_effect=[httpx.ReadTimeout("timeout"), ok_resp]), \
         patch("llm.deepseek_provider.time.sleep"):
        result = provider._call("sys", "usr")
    assert result == "ok"


def test_logs_token_usage(provider, caplog):
    with patch("llm.deepseek_provider.httpx.post", return_value=_make_response("ok")):
        provider._call("sys", "usr")


def test_factory_creates_deepseek():
    from llm.deepseek_provider import DeepSeekProvider
    from llm.factory import create_llm_provider

    s = MagicMock()
    s.llm_provider = "deepseek"
    s.llm_api_key = "test_key"
    s.llm_model = "deepseek-chat"
    s.llm_timeout = 60

    provider = create_llm_provider(s)
    assert isinstance(provider, DeepSeekProvider)
    assert provider.model == "deepseek-chat"


def test_factory_deepseek_without_api_key_raises():
    from llm.factory import create_llm_provider

    s = MagicMock()
    s.llm_provider = "deepseek"
    s.llm_api_key = None

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        create_llm_provider(s)
