import json
import re
import time

import httpx
from loguru import logger

from llm.groq_provider import INDUSTRIES_LIST


class OllamaProvider:
    """LLM-провайдер для Ollama (/api/generate). Интерфейс идентичен GroqProvider."""

    def __init__(self, base_url: str, model: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=10)
            if r.status_code != 200:
                return False
            models = [m["name"] for m in r.json().get("models", [])]
            model_base = self.model.split(":")[0]
            return any(self.model in m or m.startswith(model_base) for m in models)
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False

    def _call(self, system: str, user: str, retry: int = 0) -> str:
        prompt = f"<|system|>\n{system}\n\n<|user|>\n{user}\n\n<|assistant|>\n"
        try:
            response = httpx.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 1500},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()
        except httpx.ReadTimeout:
            if retry < 2:
                logger.warning(f"Ollama timeout, retry {retry + 1}/2")
                time.sleep(5)
                return self._call(system, user, retry=retry + 1)
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama HTTP error: {e.response.status_code} {e.response.text[:200]}")
            raise

    # ══════════════════════════════════════════════════════════════════════
    # СТУПЕНЬ 1 — Релевантность
    # ══════════════════════════════════════════════════════════════════════

    def check_relevance(self, text: str, channel_context: str | None = None) -> tuple[bool, str]:
        """Определяет релевантность поста для финтех-дайджеста."""
        system = (
            "Ты — методолог финтех-исследования в крупном российском банке. "
            "Твоя задача — фильтровать поток новостей и оставлять только то, "
            "что имеет отношение к финансовому рынку, технологиям или продуктовым "
            "изменениям. Отвечай строго JSON без пояснений и без markdown."
        )

        channel_hint = f"\nКонтекст канала: {channel_context}\n" if channel_context else ""

        user = f"""Оцени релевантность поста для финтех-исследования.

РЕЛЕВАНТНЫЕ темы:
- Финансовые продукты и услуги (банкинг, платежи, кредитование, страхование, инвестиции)
- Финтех-стартапы и финтех-продукты
- Платёжные технологии и инфраструктура
- Биометрия в платежах и идентификации
- Цифровые валюты, криптовалюты, токенизация
- ИИ и ML в финансовых продуктах, скоринге, обслуживании
- Регулирование финансового рынка (ЦБ, AML, KYC, RegTech)
- Кибербезопасность платежей и антифрод
- Импортозамещение в банковском ИТ
- Embedded finance, Open API, Open Banking
- Метавселенные, VR/AR, NFT в продуктах
- Кросс-отраслевые технологии которые применяются в финансах

НЕ РЕЛЕВАНТНЫЕ:
- Общие новости компаний без связи с финансами/технологиями
- Кадровые перестановки без продуктовых изменений
- Лайфстайл-контент, мотивация, советы
- Анонсы конференций без описания докладов
- Реклама курсов и обучающих программ
- Личные мнения и философские размышления без фактов
{channel_hint}
Пост:
{text[:2500]}

Ответ строго JSON:
{{"relevant": true, "reason": "одно предложение почему"}}"""

        raw = self._call(system, user)
        try:
            match = re.search(r'\{.*?\}', raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}
            return bool(data.get("relevant", False)), data.get("reason", "")
        except Exception as e:
            logger.warning(f"Ollama relevance parse error: {e} | raw: {raw[:100]}")
            return False, ""

    # ══════════════════════════════════════════════════════════════════════
    # СТУПЕНЬ 2 — Классификация: новость или кейс
    # ══════════════════════════════════════════════════════════════════════

    def classify_post(self, text: str, channel_context: str | None = None) -> dict:
        """Определяет: пост — это просто новость или содержит кейс(ы)."""
        system = (
            "Ты — методолог трендвотчинга в финтех-исследовании. "
            "Различаешь два типа контента: КЕЙСЫ и НОВОСТИ. Отвечай строго JSON."
        )

        channel_hint = f"\nКонтекст канала: {channel_context}\n" if channel_context else ""

        user = f"""Определи природу поста.

КЕЙС — конкретное проявление изменения в технологиях/продуктах. Все условия:
1. Есть конкретная компания (не «банки» вообще, а «Сбер», «ВТБ»)
2. Есть конкретное действие: запуск, внедрение, партнёрство, обновление
3. Есть технологическая или продуктовая суть
4. Можно сформулировать ценность для отрасли или клиента

НОВОСТЬ — событие или факт без явной иллюстрации технологического изменения:
- Изменение регуляторных параметров (ставки, нормативы, лимиты)
- Кадровые перестановки, финансовые результаты, отчётность
- Прогнозы, мнения без конкретных продуктов
- Слухи, общие обзоры, статистика, подборки

Если сомневаешься — это новость.
{channel_hint}
Пост:
{text[:3000]}

Ответ строго JSON:
{{
  "type": "case" или "news",
  "case_count": число (1+ если case, 0 если news),
  "reason": "одно предложение почему"
}}"""

        raw = self._call(system, user)
        try:
            match = re.search(r'\{.*?\}', raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}
            return {
                "type": data.get("type", "news"),
                "case_count": int(data.get("case_count", 0)),
                "reason": data.get("reason", ""),
            }
        except Exception as e:
            logger.warning(f"Ollama classify_post parse error: {e} | raw: {raw[:100]}")
            return {"type": "news", "case_count": 0, "reason": "parse error"}

    # ══════════════════════════════════════════════════════════════════════
    # СТУПЕНЬ 3a — Резюме
    # ══════════════════════════════════════════════════════════════════════

    def generate_summary(self, text: str) -> str:
        """Краткое резюме для новостей и кейсов — попадает в дайджест."""
        system = (
            "Ты — редактор финтех-дайджеста для аналитиков и исследователей рынка. "
            "Пишешь плотно, фактологично, без вводных фраз и оценочных суждений."
        )

        user = f"""Напиши краткое резюме новости в 2-3 предложениях.

Правила:
- Только факты из текста, без додумывания
- Конкретные цифры, названия компаний, даты — обязательно
- Без «В данной новости», «Резюме», «Сообщается, что»
- Без оценочных слов и советов

Пост:
{text[:2500]}

Резюме:"""

        return self._call(system, user)

    # ══════════════════════════════════════════════════════════════════════
    # СТУПЕНЬ 3b — Извлечение данных кейса
    # ══════════════════════════════════════════════════════════════════════

    def extract_cases(
        self,
        text: str,
        source_url: str | None,
        channel_context: str | None = None,
    ) -> list[dict]:
        """Извлекает структурированные данные кейсов. Без поля trend_name."""
        system = (
            "Ты — аналитик финтех-рынка. Извлекаешь структурированную информацию "
            "о кейсах строго из текста, без додумывания. Отвечай только JSON."
        )

        channel_hint = f"\nКонтекст канала: {channel_context}\n" if channel_context else ""

        user = f"""Извлеки один или несколько кейсов из поста.

Поля каждого кейса:
- case_title: короткое название (5-10 слов)
- company: каноническое короткое название компании
- description: 2-4 предложения — что произошло, факты, цифры
- how_it_works: 1-3 предложения о технической сути ИЛИ null
- value: 1-2 предложения — что меняет для отрасли или клиента
- market: "Россия" / "Мир" / "Россия и мир"
- industry: отрасль из списка: {INDUSTRIES_LIST}

Канонические имена компаний:
Сбер/Сбербанк → "Сбер", ВТБ/Банк ВТБ → "ВТБ", Альфа-Банк/АльфаБанк → "Альфа-Банк",
Тинькофф/Т-Банк → "Т-Банк", ЦБ РФ/Банк России → "Банк России",
МегаФон → "МегаФон", Газпромбанк/ГПБ → "Газпромбанк", РСХБ → "Россельхозбанк"

Правила: только факты из текста, null если данных мало, только JSON-массив.
{channel_hint}
Пост:
{text[:3000]}

Ответ строго JSON-массив:
[
  {{
    "case_title": "...",
    "company": "...",
    "description": "...",
    "how_it_works": "..." или null,
    "value": "...",
    "market": "Россия" или "Мир" или "Россия и мир",
    "industry": "одна из отраслей выше"
  }}
]"""

        raw = self._call(system, user)
        try:
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            cases = json.loads(match.group()) if match else []
            if not isinstance(cases, list):
                return []
            for case in cases:
                case["source_url"] = source_url
            return cases
        except Exception as e:
            logger.warning(f"Ollama cases parse error: {e} | raw: {raw[:200]}")
            return []

    # ══════════════════════════════════════════════════════════════════════
    # СТУПЕНЬ 4 — Привязка к канонической базе трендов
    # ══════════════════════════════════════════════════════════════════════

    def assign_trend(self, case: dict, existing_trends: list[dict]) -> dict:
        """
        Привязывает кейс к одному из существующих трендов или предлагает новый.
        existing_trends — [{"id": 1, "name": "...", "description": "...", "category": "..."}, ...]
        """
        system = (
            "Ты — методолог трендвотчинга в финтех-исследовании. "
            "Опираешься на чёткие методологические критерии тренда. "
            "Отвечай строго JSON."
        )

        trends_text = "\n".join(
            f"{t['id']}. {t['name']} ({t.get('category', '—')}) — {t['description']}"
            for t in existing_trends
        )

        user = f"""КЕЙС:
Название: {case.get('case_title', '')}
Компания: {case.get('company', '')}
Описание: {case.get('description', '')}
Технология: {case.get('how_it_works') or '—'}
Ценность: {case.get('value', '')}
Отрасль: {case.get('industry', '')}
Рынок: {case.get('market', '')}

СУЩЕСТВУЮЩИЕ ТРЕНДЫ:
{trends_text}

ЗАДАЧА: привязать кейс к тренду.

ПРАВИЛА:
1. "existing" — кейс иллюстрирует один из существующих трендов (частый случай)
2. "new" — только если кейс не подходит ни под один тренд И образует долгосрочное
   направление (12+ месяцев). Редкое исключение.
3. "none" — кейс не подходит ни под тренды, ни образует новое направление.

По умолчанию выбирай existing или none.

Ответ строго JSON:
{{
  "decision": "existing" или "new" или "none",
  "trend_id": число (только для existing) или null,
  "new_trend_name": "название" (только для new) или null,
  "new_trend_description": "2-3 предложения" (только для new) или null,
  "reasoning": "одно-два предложения"
}}"""

        raw = self._call(system, user)
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}
            return {
                "decision": data.get("decision", "none"),
                "trend_id": data.get("trend_id"),
                "new_trend_name": data.get("new_trend_name"),
                "new_trend_description": data.get("new_trend_description"),
                "reasoning": data.get("reasoning", ""),
            }
        except Exception as e:
            logger.warning(f"Ollama assign_trend parse error: {e} | raw: {raw[:200]}")
            return {
                "decision": "none", "trend_id": None,
                "new_trend_name": None, "new_trend_description": None,
                "reasoning": "parse error",
            }
