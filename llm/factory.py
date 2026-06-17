from loguru import logger

from config.settings import Settings


def create_llm_provider(settings: Settings):
    """Возвращает LLM-провайдер по настройке llm_provider."""
    provider_name = settings.llm_provider.lower()

    if provider_name == "groq":
        from llm.groq_provider import GroqProvider
        if not settings.llm_api_key:
            raise ValueError("Для Groq нужен LLM_API_KEY в .env")
        logger.info(f"Using Groq provider: {settings.llm_model}")
        return GroqProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout,
        )

    if provider_name == "ollama":
        from llm.ollama_provider import OllamaProvider
        if not settings.llm_base_url:
            raise ValueError("Для Ollama нужен LLM_BASE_URL в .env")
        logger.info(f"Using Ollama provider: {settings.llm_model} @ {settings.llm_base_url}")
        return OllamaProvider(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout=settings.llm_timeout,
        )

    raise ValueError(f"Неизвестный LLM провайдер: {provider_name!r}. Используйте 'groq' или 'ollama'")
