"""Tests for YandexProvider: model URI, headers, retry logic, response parsing."""
import json
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from llm.yandex_provider import YANDEX_API_URL, YandexProvider


@pytest.fixture
def provider():
    return YandexProvider(api_key="test-key", folder_id="folder123", model="aliceai-llm/latest")


class TestModelUri:
    def test_auto_builds_gpt_uri(self):
        p = YandexProvider(api_key="k", folder_id="f123", model="aliceai-llm/latest")
        assert p.model == "gpt://f123/aliceai-llm/latest"

    def test_does_not_double_wrap_full_uri(self):
        full = "gpt://f123/aliceai-llm/latest"
        p = YandexProvider(api_key="k", folder_id="f123", model=full)
        assert p.model == full

    def test_custom_model_name(self):
        p = YandexProvider(api_key="k", folder_id="myfolder", model="yandexgpt/latest")
        assert p.model == "gpt://myfolder/yandexgpt/latest"


class TestApiCall:
    def _mock_response(self, content: str, status: int = 200):
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = {
            "choices": [{"message": {"content": content}}]
        }
        resp.raise_for_status = MagicMock()
        return resp

    def test_uses_api_key_header(self, provider):
        resp = self._mock_response('{"relevant": true, "reason": "ok"}')
        with patch("llm.yandex_provider.httpx.post", return_value=resp) as mock_post:
            provider.check_relevance("some text")
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Api-Key test-key"

    def test_does_not_use_bearer_header(self, provider):
        resp = self._mock_response('{"relevant": true, "reason": "ok"}')
        with patch("llm.yandex_provider.httpx.post", return_value=resp) as mock_post:
            provider.check_relevance("some text")
        _, kwargs = mock_post.call_args
        assert not kwargs["headers"]["Authorization"].startswith("Bearer")

    def test_posts_to_correct_endpoint(self, provider):
        resp = self._mock_response('{"relevant": false, "reason": "nope"}')
        with patch("llm.yandex_provider.httpx.post", return_value=resp) as mock_post:
            provider.check_relevance("some text")
        args, _ = mock_post.call_args
        assert args[0] == YANDEX_API_URL

    def test_retry_on_429(self, provider):
        rate_limit_resp = MagicMock()
        rate_limit_resp.status_code = 429
        rate_limit_resp.text = "rate limit"
        error = httpx.HTTPStatusError("429", request=MagicMock(), response=rate_limit_resp)
        rate_limit_resp.raise_for_status.side_effect = error

        ok_resp = self._mock_response('{"relevant": true, "reason": "ok"}')

        with patch("llm.yandex_provider.httpx.post", side_effect=[rate_limit_resp, ok_resp]), \
             patch("llm.yandex_provider.time.sleep"):
            relevant, _ = provider.check_relevance("text")
        assert relevant is True

    def test_retry_on_read_timeout(self, provider):
        ok_resp = self._mock_response('{"relevant": false, "reason": "no"}')
        with patch("llm.yandex_provider.httpx.post",
                   side_effect=[httpx.ReadTimeout("timeout"), ok_resp]), \
             patch("llm.yandex_provider.time.sleep"):
            relevant, _ = provider.check_relevance("text")
        assert relevant is False

    def test_401_raises_immediately(self, provider):
        auth_resp = MagicMock()
        auth_resp.status_code = 401
        auth_resp.text = "unauthorized"
        error = httpx.HTTPStatusError("401", request=MagicMock(), response=auth_resp)
        auth_resp.raise_for_status.side_effect = error

        with patch("llm.yandex_provider.httpx.post", return_value=auth_resp), \
             patch("llm.yandex_provider.time.sleep") as sleep_mock:
            with pytest.raises(httpx.HTTPStatusError):
                provider.check_relevance("text")
        sleep_mock.assert_not_called()


class TestCheckRelevance:
    def _post(self, content):
        resp = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        resp.raise_for_status = MagicMock()
        return resp

    def test_relevant_true(self, provider):
        with patch("llm.yandex_provider.httpx.post",
                   return_value=self._post('{"relevant": true, "reason": "fintech"}')):
            rel, reason = provider.check_relevance("Сбер запустил новый сервис")
        assert rel is True
        assert reason == "fintech"

    def test_relevant_false(self, provider):
        with patch("llm.yandex_provider.httpx.post",
                   return_value=self._post('{"relevant": false, "reason": "off-topic"}')):
            rel, _ = provider.check_relevance("Рецепт борща")
        assert rel is False

    def test_parse_error_returns_false(self, provider):
        with patch("llm.yandex_provider.httpx.post",
                   return_value=self._post("не JSON вообще")):
            rel, _ = provider.check_relevance("text")
        assert rel is False


class TestExtractCases:
    def _post(self, content):
        resp = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": content}}]}
        resp.raise_for_status = MagicMock()
        return resp

    def test_returns_list_with_source_url(self, provider):
        raw = json.dumps([{
            "case_title": "Сбер Face Pay",
            "company": "Сбер",
            "description": "desc",
            "how_it_works": "hw",
            "value": "v",
            "market": "Россия",
            "industry": "Финтех / банки",
        }])
        with patch("llm.yandex_provider.httpx.post", return_value=self._post(raw)):
            cases = provider.extract_cases("text", "https://t.me/sber/1")
        assert len(cases) == 1
        assert cases[0]["source_url"] == "https://t.me/sber/1"
        assert cases[0]["company"] == "Сбер"

    def test_malformed_json_returns_empty(self, provider):
        with patch("llm.yandex_provider.httpx.post", return_value=self._post("garbage")):
            cases = provider.extract_cases("text", None)
        assert cases == []
