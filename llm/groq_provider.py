import json
import re
import time

import httpx
from loguru import logger

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider:
    def __init__(self, api_key: str, model: str, timeout: int = 60):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            r = httpx.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    def _call(self, system: str, user: str, retry: int = 0) -> str:
        try:
            response = httpx.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1500,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and retry < 3:
                wait = 60 * (retry + 1)  # 60, 120, 180 секунд
                logger.warning(f"Rate limit hit, waiting {wait}s (retry {retry + 1}/3)")
                time.sleep(wait)
                return self._call(system, user, retry=retry + 1)
            raise

    def check_relevance(self, text: str) -> tuple[bool, str]:
        system = """Ты — аналитик корпоративного дайджеста российского банка.
Оцени релевантность новости для тематик:
финтех, банки, платежи, биометрия, КСО/самообслуживание, ИИ,
ИТ-инфраструктура, импортозамещение, кибербезопасность, HR,
обучение, регуляторика, МСБ, розница, клиентский сервис.
Отвечай строго JSON без пояснений."""

        user = f"""Новость:
{text[:2000]}

Ответ строго в формате:
{{"relevant": true, "reason": "одно предложение почему"}}"""

        raw = self._call(system, user)
        try:
            match = re.search(r'\{.*?\}', raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}
            return bool(data.get("relevant", False)), data.get("reason", "")
        except Exception as e:
            logger.warning(f"relevance parse error: {e} | raw: {raw[:100]}")
            return False, ""

    def generate_summary(self, text: str) -> str:
        """Краткое резюме для сайта — 2-3 предложения для руководителей и сотрудников."""
        system = """Ты — редактор корпоративного портала российского банка.
Напиши краткое резюме новости в 2-3 предложениях.
Пиши просто и понятно — для занятых руководителей без технического бэкграунда.
Только факты, никаких вводных слов типа "В данной новости" или "Резюме:"."""

        user = f"""Новость:
{text[:2000]}

Краткое резюме (2-3 предложения):"""

        return self._call(system, user)

    def extract_cases(self, text: str, source_url: str | None) -> list[dict]:
        """Структурированные кейсы для аналитиков."""
        system = """Ты — аналитик корпоративного дайджеста российского банка.
Извлекай кейсы строго из текста, не выдумывай факты.
Отвечай только JSON без пояснений и без markdown."""

        user = f"""Из новости извлеки один или несколько кейсов.
Кейс — конкретный продукт, технология или событие с понятной ценностью.

Новость:
{text[:3000]}

Ответ строго в формате JSON-массива:
[
  {{
    "trend_name": "название тренда (например: Биометрические платежи)",
    "case_title": "короткое название кейса",
    "company": "главная компания или организация",
    "description": "2-4 предложения: что произошло и в чём суть",
    "how_it_works": "1-3 предложения: как технически работает, или null если нет информации",
    "value": "1-2 предложения: зачем это важно для банковской отрасли",
    "market": "Россия или Мир или Россия и мир"
  }}
]

Правила:
- Null если информации недостаточно для поля
- Только факты из текста, без додумывания
- Все поля на русском языке
- Только JSON, никакого текста до или после"""

        raw = self._call(system, user)
        try:
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            cases = json.loads(match.group()) if match else []
            for case in cases:
                case["source_url"] = source_url
            return cases if isinstance(cases, list) else []
        except Exception as e:
            logger.warning(f"cases parse error: {e} | raw: {raw[:200]}")
            return []
