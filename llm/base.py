from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    """Базовый класс для LLM-провайдеров. Будет использован на следующем этапе."""

    @abstractmethod
    def summarize(self, text: str) -> str: ...

    @abstractmethod
    def extract_entities(self, text: str) -> dict: ...

    @abstractmethod
    def classify_topics(self, text: str) -> list[str]: ...
