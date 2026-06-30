"""Tests for create_llm_provider: all 3 providers + unknown provider error."""
from unittest.mock import MagicMock, patch

import pytest

from llm.factory import create_llm_provider


def _settings(**kwargs):
    s = MagicMock()
    s.llm_provider = kwargs.get("llm_provider", "groq")
    s.llm_api_key = kwargs.get("llm_api_key", "test-key")
    s.llm_model = kwargs.get("llm_model", "llama-3.3-70b-versatile")
    s.llm_base_url = kwargs.get("llm_base_url", "http://localhost:11434")
    s.llm_timeout = kwargs.get("llm_timeout", 60)
    s.yandex_api_key = kwargs.get("yandex_api_key", "yandex-key")
    s.yandex_folder_id = kwargs.get("yandex_folder_id", "folder123")
    s.yandex_model = kwargs.get("yandex_model", "aliceai-llm/latest")
    return s


class TestGroqProvider:
    def test_creates_groq_provider(self):
        from llm.groq_provider import GroqProvider
        provider = create_llm_provider(_settings(llm_provider="groq"))
        assert isinstance(provider, GroqProvider)

    def test_groq_without_api_key_raises(self):
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            create_llm_provider(_settings(llm_provider="groq", llm_api_key=None))

    def test_groq_case_insensitive(self):
        from llm.groq_provider import GroqProvider
        provider = create_llm_provider(_settings(llm_provider="GROQ"))
        assert isinstance(provider, GroqProvider)


class TestOllamaProvider:
    def test_creates_ollama_provider(self):
        from llm.ollama_provider import OllamaProvider
        provider = create_llm_provider(_settings(llm_provider="ollama"))
        assert isinstance(provider, OllamaProvider)

    def test_ollama_without_base_url_raises(self):
        with pytest.raises(ValueError, match="LLM_BASE_URL"):
            create_llm_provider(_settings(llm_provider="ollama", llm_base_url=None))


class TestYandexProvider:
    def test_creates_yandex_provider(self):
        from llm.yandex_provider import YandexProvider
        provider = create_llm_provider(_settings(llm_provider="yandex"))
        assert isinstance(provider, YandexProvider)

    def test_yandex_without_api_key_raises(self):
        with pytest.raises(ValueError, match="YANDEX_API_KEY"):
            create_llm_provider(_settings(llm_provider="yandex", yandex_api_key=None))

    def test_yandex_without_folder_id_raises(self):
        with pytest.raises(ValueError, match="YANDEX_FOLDER_ID"):
            create_llm_provider(_settings(llm_provider="yandex", yandex_folder_id=None))

    def test_yandex_model_uri_built_correctly(self):
        provider = create_llm_provider(_settings(
            llm_provider="yandex",
            yandex_folder_id="myfolder",
            yandex_model="aliceai-llm/latest",
        ))
        assert provider.model == "gpt://myfolder/aliceai-llm/latest"


class TestUnknownProvider:
    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_llm_provider(_settings(llm_provider="openai"))

    def test_unknown_provider_message_includes_name(self):
        with pytest.raises(ValueError, match="gpt4all"):
            create_llm_provider(_settings(llm_provider="gpt4all"))
