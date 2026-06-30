"""
LLM-провайдер для Yandex AI Studio (Alice AI).

Эндпоинт: https://ai.api.cloud.yandex.net/v1/chat/completions
Авторизация: заголовок "Authorization: Api-Key <ключ>" (не Bearer/IAM-токен)
Модель: gpt://<folder_id>/aliceai-llm/latest
Формат запроса/ответа: OpenAI Chat Completions API (совместимый)
"""
import json
import re
import time

import httpx
from loguru import logger

YANDEX_API_URL = "https://ai.api.cloud.yandex.net/v1/chat/completions"

INDUSTRIES_LIST = (
    "Финтех / банки, Ритейл / e-commerce, Телеком, ИТ / разработка ПО, "
    "Промышленность, Госсектор / регуляторика, Образование, Здравоохранение, "
    "Транспорт / логистика, Медиа / контент, Другое"
)


class YandexProvider:
    """
    LLM-провайдер для Yandex AI Studio.
    Использует OpenAI-совместимый эндпоинт Яндекса.
    Авторизация через Api-Key (не Bearer/IAM-токен).
    """

    def __init__(
        self,
        api_key: str,
        folder_id: str,
        model: str = "aliceai-llm/latest",
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key
        self.folder_id = folder_id
        # Формируем полный URI модели: gpt://<folder_id>/<model>
        if model.startswith("gpt://"):
            self.model = model
        else:
            self.model = f"gpt://{folder_id}/{model}"
        self.timeout = timeout

    def is_available(self) -> bool:
        """Проверяет доступность Yandex AI Studio минимальным запросом."""
        try:
            response = httpx.post(
                YANDEX_API_URL,
                headers={
                    "Authorization": f"Api-Key {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                    "temperature": 0.1,
                },
                timeout=15,
            )
            # 200 = OK, 400 = плохой запрос, но API доступен
            return response.status_code in (200, 400)
        except Exception as e:
            logger.warning(f"Yandex AI availability check failed: {e}")
            return False

    def _call(self, system: str, user: str, retry: int = 0) -> str:
        """
        Отправляет запрос к Yandex AI Studio через OpenAI-совместимый эндпоинт.
        Авторизация: Api-Key (не Bearer).
        """
        try:
            response = httpx.post(
                YANDEX_API_URL,
                headers={
                    "Authorization": f"Api-Key {self.api_key}",
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
            status = e.response.status_code
            body = e.response.text[:300]
            if status == 429 and retry < 3:
                wait = 60 * (retry + 1)
                logger.warning(f"Yandex rate limit, waiting {wait}s (retry {retry + 1}/3)")
                time.sleep(wait)
                return self._call(system, user, retry=retry + 1)
            if status == 401:
                logger.error("Yandex API auth error: check YANDEX_API_KEY and YANDEX_FOLDER_ID")
                raise
            logger.error(f"Yandex API error {status}: {body}")
            raise

        except httpx.ReadTimeout:
            if retry < 2:
                logger.warning(f"Yandex timeout, retry {retry + 1}/2")
                time.sleep(5)
                return self._call(system, user, retry=retry + 1)
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
- Кросс-отраслевые технологии которые применяются в финансах (ИИ, голосовые интерфейсы, биометрия)

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
            logger.warning(f"relevance parse error: {e} | raw: {raw[:100]}")
            return False, ""

    # ══════════════════════════════════════════════════════════════════════
    # СТУПЕНЬ 2 — Классификация: новость или кейс
    # ══════════════════════════════════════════════════════════════════════

    def classify_post(self, text: str, channel_context: str | None = None) -> dict:
        """
        Определяет: пост — это просто новость или содержит кейс(ы).
        Возвращает: {"type": "case"|"news", "reason": str, "case_count": int}
        """
        system = (
            "Ты — методолог трендвотчинга в финтех-исследовании. "
            "Различаешь два типа контента: КЕЙСЫ (иллюстрации технологических "
            "и продуктовых изменений) и НОВОСТИ (события и факты без явной "
            "иллюстрации изменений). Отвечай строго JSON."
        )

        channel_hint = f"\nКонтекст канала: {channel_context}\n" if channel_context else ""

        user = f"""Определи природу поста.

КЕЙС — это конкретное проявление изменения в технологиях, продуктах или
бизнес-моделях. Должны выполняться ВСЕ условия:
1. Есть конкретная компания/организация (не «банки» вообще, а «Сбер», «ВТБ»)
2. Есть конкретное действие: запуск, внедрение, партнёрство, значимое обновление
3. Есть технологическая или продуктовая суть (что именно сделано, какая технология)
4. Можно сформулировать ценность (зачем это, что меняет для отрасли или клиента)

НОВОСТЬ — это событие или факт без явной иллюстрации технологического изменения.
Признаки новости:
- Изменение регуляторных параметров (ставки, нормативы, лимиты)
- Кадровые перестановки
- Финансовые результаты компании, отчётность
- Открытие/закрытие отделений, общие операционные новости
- Прогнозы аналитиков, мнения экспертов без описания конкретных продуктов
- Слухи, общие обзоры рынка
- Статистика и исследования без привязки к конкретному продукту
- Подборки и дайджесты «что произошло за неделю»

Если в посте несколько кейсов (подборка запусков, обзор нескольких компаний) —
укажи это в case_count.

Один и тот же пост не может быть и кейсом, и новостью — выбери что точнее
отражает суть. Если сомневаешься — это новость.
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
            logger.warning(f"classify_post parse error: {e} | raw: {raw[:100]}")
            return {"type": "news", "case_count": 0, "reason": "parse error"}

    # ══════════════════════════════════════════════════════════════════════
    # СТУПЕНЬ 3a — Резюме для новостей
    # ══════════════════════════════════════════════════════════════════════

    def generate_summary(self, text: str) -> str:
        """Краткое резюме для новостей и кейсов — попадает в дайджест."""
        system = (
            "Ты — редактор финтех-дайджеста для аналитиков и исследователей рынка. "
            "Пишешь плотно, фактологично, без вводных фраз и оценочных суждений. "
            "Целевая аудитория — профессионалы, не нужно объяснять базовые понятия."
        )

        user = f"""Напиши краткое резюме новости в 2-3 предложениях.

Правила:
- Только факты из текста, без додумывания
- Конкретные цифры, названия компаний, даты — обязательно
- Без «В данной новости», «Резюме», «Сообщается, что»
- Без оценочных слов («важный», «значимый», «прорывной»)
- Без советов и рекомендаций

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
        """
        Извлекает структурированные данные кейсов из поста.
        Не возвращает trend_name — привязка к тренду делается отдельно через assign_trend.
        """
        system = (
            "Ты — аналитик финтех-рынка. Извлекаешь структурированную информацию "
            "о кейсах строго из текста, без додумывания. Отвечай только JSON."
        )

        channel_hint = f"\nКонтекст канала: {channel_context}\n" if channel_context else ""

        user = f"""Извлеки один или несколько кейсов из поста.
Каждый кейс — конкретное действие конкретной компании с понятной сутью.

Поля каждого кейса:
- case_title: короткое название кейса (5-10 слов, без воды)
  Пример: "Сбер запустил Face Pay в 15 000 банкоматов"
- company: каноническое короткое название компании
- description: 2-4 предложения — что произошло, конкретные факты, цифры
- how_it_works: 1-3 предложения о технической сути ИЛИ null если нет информации
- value: 1-2 предложения — что это меняет для отрасли или клиента
- market: "Россия" / "Мир" / "Россия и мир"
- industry: отрасль из списка ниже (одно значение)

ОТРАСЛИ (выбрать одну):
{INDUSTRIES_LIST}

Канонические имена компаний (без ПАО/АО/ООО):
- Сбер / Сбербанк / ПАО Сбербанк → "Сбер"
- ВТБ / Банк ВТБ / ПАО ВТБ → "ВТБ"
- Альфа-Банк / АльфаБанк / Альфа Банк → "Альфа-Банк"
- Тинькофф / Т-Банк / ТКС → "Т-Банк"
- Центральный Банк / ЦБ РФ / Банк России → "Банк России"
- МегаФон / Мегафон → "МегаФон"
- Россельхозбанк / РСХБ → "Россельхозбанк"
- Газпромбанк / ГПБ → "Газпромбанк"
- Если несколько компаний — выбери одну главную (которая делает действие)

Правила:
- Только факты из текста — без додумывания
- null если данных недостаточно для поля
- Все поля на русском языке
- Только JSON-массив, никакого текста до или после
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
            logger.warning(f"cases parse error: {e} | raw: {raw[:200]}")
            return []

    # ══════════════════════════════════════════════════════════════════════
    # СТУПЕНЬ 4 — Привязка кейса к канонической базе трендов
    # ══════════════════════════════════════════════════════════════════════

    def assign_trend(self, case: dict, existing_trends: list[dict]) -> dict:
        """
        Привязывает кейс к одному из существующих трендов или предлагает новый.
        existing_trends — [{"id": 1, "name": "...", "description": "...", "category": "..."}, ...]
        Возвращает: {"decision": "existing"|"new"|"none", "trend_id": int|None,
                     "new_trend_name": str|None, "new_trend_description": str|None,
                     "reasoning": str}
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

        user = f"""МЕТОДОЛОГИЯ ТРЕНДА:

Тренд — направление изменений в технологиях и продуктах, которое показывает
как появляются новые решения и меняются существующие. Горизонт устойчивости
тренда — не меньше 12-18 месяцев.

Тренд это НЕ:
- Конкретный продукт одной компании (это кейс)
- Кратковременная акция или маркетинговая кампания
- Локальное регуляторное изменение
- Финансовый показатель или отчёт
- Единичное событие без признаков повторяемости в отрасли

═══════════════════════════════════════════════════════════════════════

КЕЙС:
Название: {case.get('case_title', '')}
Компания: {case.get('company', '')}
Описание: {case.get('description', '')}
Технология/механизм: {case.get('how_it_works') or '—'}
Ценность: {case.get('value', '')}
Отрасль: {case.get('industry', '')}
Рынок: {case.get('market', '')}

═══════════════════════════════════════════════════════════════════════

СУЩЕСТВУЮЩИЕ ТРЕНДЫ В НАШЕЙ БАЗЕ:
{trends_text}

═══════════════════════════════════════════════════════════════════════

ЗАДАЧА: привязать кейс к одному из существующих трендов ИЛИ принять решение
о новом тренде ИЛИ оставить без тренда.

ПРАВИЛА:

1. "existing" — кейс явно иллюстрирует один из существующих трендов.
   Это самый частый случай. Выбирай existing если кейс подходит хотя бы частично.

2. "new" — только когда выполнены ВСЕ условия:
   - Кейс не подходит ни под один существующий тренд
   - Кейс является чётким примером нового долгосрочного направления
     (горизонт 12+ месяцев, фундаментальность, широкое применение)
   - Ты можешь сформулировать название и описание тренда

3. "none" — кейс не подходит под существующие тренды и не образует
   новое направление (единичная инициатива или нишевое решение).

ВАЖНО: создание новых трендов — редкое исключение. По умолчанию выбирай
existing или none. Не предлагай новый тренд если есть похожий существующий.

Ответ строго JSON:
{{
  "decision": "existing" или "new" или "none",
  "trend_id": число (только для existing) или null,
  "new_trend_name": "название" (только для new) или null,
  "new_trend_description": "2-3 предложения" (только для new) или null,
  "reasoning": "одно-два предложения почему такое решение"
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
            logger.warning(f"assign_trend parse error: {e} | raw: {raw[:200]}")
            return {
                "decision": "none", "trend_id": None,
                "new_trend_name": None, "new_trend_description": None,
                "reasoning": "parse error",
            }
