import sys
from functools import lru_cache

from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # API ID приложения Telegram.
    telegram_api_id: int
    # API hash приложения Telegram.
    telegram_api_hash: str
    # Номер телефона Telegram-аккаунта.
    telegram_phone: str
    # Имя файла сессии Telethon.
    telegram_session_name: str = "tg_news"
    # Путь к SQLite-базе данных.
    db_path: str = "data/tg_news.db"
    # Путь к YAML-файлу со списком источников.
    sources_file: str = "sources.yaml"
    # Уровень логирования приложения.
    log_level: str = "INFO"
    # Количество дней для сбора новостей по умолчанию.
    default_collect_days: int = 7
    # Минимальный балл релевантности новости.
    min_relevance_score: int = 30
    # LLM-обогащение через Groq API.
    llm_enabled: bool = False
    llm_provider: str = "groq"
    llm_api_key: str | None = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_timeout: int = 60
    llm_min_score: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def setup_logging() -> None:
    settings = get_settings()
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
    )
