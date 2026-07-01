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

    if provider_name == "deepseek":
        from llm.deepseek_provider import DeepSeekProvider
        if not settings.llm_api_key:
            raise ValueError("Для DeepSeek нужен LLM_API_KEY в .env")
        logger.info(f"Using DeepSeek provider: {settings.llm_model} via artemox proxy")
        return DeepSeekProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout,
        )

    if provider_name == "yandex":
        from llm.yandex_provider import YandexProvider
        if not settings.yandex_api_key:
            raise ValueError("Для Yandex нужен YANDEX_API_KEY в .env")
        if not settings.yandex_folder_id:
            raise ValueError("Для Yandex нужен YANDEX_FOLDER_ID в .env")
        logger.info(
            f"Using Yandex AI provider: {settings.yandex_model}"
            f" (folder: {settings.yandex_folder_id})"
        )
        return YandexProvider(
            api_key=settings.yandex_api_key,
            folder_id=settings.yandex_folder_id,
            model=settings.yandex_model,
            timeout=settings.llm_timeout,
        )

    raise ValueError(
        f"Unknown LLM provider: {provider_name!r}. Use 'groq', 'ollama', 'yandex' or 'deepseek'"
    )


def create_fallback_provider(settings) -> object | None:
    """
    Создаёт резервный Groq-провайдер если задан GROQ_FALLBACK_API_KEY.
    Возвращает None если ключ не задан.
    """
    if not settings.groq_fallback_api_key:
        return None
    try:
        from llm.groq_provider import GroqProvider
        logger.info(f"Fallback provider: Groq ({settings.groq_fallback_model})")
        return GroqProvider(
            api_key=settings.groq_fallback_api_key,
            model=settings.groq_fallback_model,
            timeout=settings.llm_timeout,
        )
    except Exception as e:
        logger.warning(f"Failed to create fallback provider: {e}")
        return None
