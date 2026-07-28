"""Tests: per-call timeout override in LLM providers."""
from unittest.mock import MagicMock, patch


def _make_mock_response(content: str = "ok") -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {
        "choices": [{"message": {"content": content}}],
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
