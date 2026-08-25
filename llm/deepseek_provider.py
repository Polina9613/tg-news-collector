"""
LLM-провайдер для официального DeepSeek API (api.deepseek.com).

Эндпоинт: https://api.deepseek.com/chat/completions
Авторизация: Authorization: Bearer <ключ>
Модель: deepseek-chat (НЕ reasoning-модель по умолчанию)
Формат: OpenAI Chat Completions API
"""
import json
import re
import time

import httpx
from loguru import logger

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

INDUSTRIES_LIST = (
    "Финтех / банки, Ритейл / e-commerce, Телеком, ИТ / разработка ПО, "
    "Промышленность, Госсектор / регуляторика, Образование, Здравоохранение, "
    "Транспорт / логистика, Медиа / контент, Другое"
)

# ── Статические системные промпты (кэшируются DeepSeek после первого вызова) ──

_RELEVANCE_SYSTEM = """Ты — аналитик финтех-исследования в крупном российском банке.
Оцениваешь релевантность постов из Telegram-каналов и определяешь их тип.

РЕЛЕВАНТНЫЕ ТЕМЫ:
- Финансовые продукты и услуги (банкинг, платежи, кредитование, страхование)
- Финтех-стартапы и финтех-продукты
- Платёжные технологии и инфраструктура
- Биометрия в платежах и идентификации
- Цифровые валюты, криптовалюты, токенизация
- ИИ и ML в финансовых продуктах, скоринге, обслуживании
- Регулирование финансового рынка (ЦБ, AML, KYC, RegTech)
- Кибербезопасность платежей и антифрод
- Импортозамещение в банковском ИТ
- Embedded finance, Open API, Open Banking

НЕРЕЛЕВАНТНЫЕ ТЕМЫ:
- Лайфстайл без связи с финансами
- Общие ИИ-новости без финансового контекста
- Реклама курсов и обучения
- Кадровые новости без продуктовой сути
- Спорт, мода, развлечения

ТИП ПОСТА — один из трёх:

КЕЙС (case) = одна конкретная компания/организация + одно конкретное действие
(запуск, внедрение, партнёрство) + технологическая суть + измеримая ценность.
У кейса всегда есть чёткий "герой" — кто именно что сделал.

НОВОСТЬ (news) = событие или факт без продуктовой конкретики:
изменение ставок, кадровые перестановки, финрезультаты, единичное
заявление без деталей механизма.

ОБЗОР (digest) = пост упоминающий НЕСКОЛЬКО разных компаний/проектов/систем
БЕЗ единого действующего лица — подборки, обзоры технологий с примерами,
сводки "что вышло за неделю", списки/классификации, дайджесты новостей.
Признаки: несколько равнозначных упоминаний в одном посте, слова
"обзор", "подборка", "примеры", "среди систем", "дайджест", "топ",
отсутствие единой компании-героя (или компания указана как "мир"/
"разное"/не названа).

Если пост упоминает 2+ разных компаний/проектов КАК РАВНОЗНАЧНЫЕ ПРИМЕРЫ
в рамках одной темы — это ВСЕГДА digest, не case, даже если каждый пример
выглядит интересным. Один case — это всегда один герой с одним действием.

При сомнении между case и digest — выбирай digest.

Отвечай строго JSON без пояснений и markdown."""

_ASSIGN_TREND_SYSTEM_TEMPLATE = """Ты — методолог трендвотчинга в финтех-исследовании.

ОПРЕДЕЛЕНИЕ ТРЕНДА:
Тренд — направление изменений в технологиях и продуктах с горизонтом 12-18 месяцев.
Сила тренда: влияние на пользовательский путь, фундаментальность,
стратегическая значимость, широта применимости, вероятность закрепления.

ЭТО НЕ ТРЕНД:
- Конкретный продукт одной компании (это кейс)
- Кратковременная акция или маркетинговая кампания
- Локальное регуляторное изменение
- Финансовый показатель

СУЩЕСТВУЮЩИЕ ТРЕНДЫ В БАЗЕ:
{trends_list}

ПРАВИЛА РЕШЕНИЯ:
"existing" — кейс подходит под один из трендов выше (самый частый случай)
"new" — ТОЛЬКО если кейс не подходит ни под один тренд И является чётким примером
         нового долгосрочного направления (горизонт 12+ месяцев)
"none" — кейс единичный, не образует направления

По умолчанию выбирай "existing" или "none". "new" — редкое исключение.
Отвечай строго JSON без пояснений."""

_EXTRACT_CASES_SYSTEM = """Ты — аналитик финтех-рынка, готовящий дайджест
для команды трендвотчинга крупного российского банка.

ВАЖНО — company: это компания УПОМЯНУТАЯ В ТЕКСТЕ ПОСТА.
Если в тексте нет явного названия компании — поставь null.
НЕ используй название канала как компанию.
Пример: пост в канале @sberbank про стороннюю компанию → company = та компания, не Сбер.

КАНОНИЧЕСКИЕ ИМЕНА КОМПАНИЙ (без ПАО/АО/ООО):
Сбер / Сбербанк / ПАО Сбербанк → "Сбер"
ВТБ / Банк ВТБ / ПАО ВТБ → "ВТБ"
Альфа-Банк / АльфаБанк → "Альфа-Банк"
Тинькофф / Т-Банк / ТКС → "Т-Банк"
ЦБ РФ / Банк России / Центробанк → "Банк России"
МегаФон / Мегафон → "МегаФон"
Россельхозбанк / РСХБ → "Россельхозбанк"
Газпромбанк / ГПБ → "Газпромбанк"
Если несколько компаний — выбери одну главную.

ОТРАСЛИ (выбрать одну):
Финтех / банки, Ритейл / e-commerce, Телеком, ИТ / разработка ПО,
Промышленность, Госсектор / регуляторика, Образование, Здравоохранение,
Транспорт / логистика, Медиа / контент, Другое

ОЦЕНКА ВАЖНОСТИ КЕЙСА (importance_score, 0-100):
Читатель — аналитик банка, который следит за тем как технологии и продукты
меняют финансовую отрасль, и должен принимать решения о том куда банку
двигаться дальше. Оценивай важность именно для ЭТОЙ аудитории.

ВЫСОКИЙ балл (80-100) — кейс прямо касается банковских технологий и продуктов:
— Банк/финтех-компания запускает новый продукт, технологию, партнёрство
— Платежи, биометрия, ИИ в банкинге/скоринге/обслуживании клиентов
— Регулирование финансового рынка, ЦБ, законы о криптовалюте/цифровом рубле
— Кибербезопасность и антифрод в финансовых операциях
— Крупная сделка/инвестиция/санкции затрагивающие банк или платёжную систему
— Технологии (ИИ-агенты, биометрия, блокчейн) применимые в банке,
  даже если пример взят из другой отрасли (ритейл, телеком)

СРЕДНИЙ балл (50-79) — косвенно полезно для трендвотчинга:
— Общие технологические тренды без прямой привязки к финансам,
  но потенциально применимые в банке
— Кейсы других отраслей с паттерном интересным для банка

НИЗКИЙ балл (0-49) — на периферии интереса аналитика банка:
— Технологические новости без связи с финансами, платежами, банкингом
— Корпоративные новости без продуктового/технологического контекста
— Общественно-политические новости без прямого влияния на финтех-рынок

Внутри диапазона: крупная компания + измеримый эффект + новизна → выше.

Отвечай только JSON-массивом без пояснений и markdown."""


_IMPORTANCE_BATCH_SYSTEM = """Ты — аналитик, готовящий дайджест для команды
трендвотчинга крупного российского банка. Оцениваешь важность уже
извлечённых кейсов — без доступа к исходному тексту поста, только по кратким описаниям.

Читатель — аналитик банка, следящий за технологиями и продуктами меняющими
финансовую отрасль. Оценивай важность именно для этой аудитории.

ВЫСОКИЙ балл (80-100): банковские технологии и продукты, платежи, биометрия,
ИИ в банкинге/скоринге, регулирование финрынка, кибербезопасность финансов,
крупные сделки/санкции затрагивающие банки, применимые к банку технологии
из других отраслей.

СРЕДНИЙ балл (50-79): общие технологические тренды применимые к банку косвенно.

НИЗКИЙ балл (0-49): технологии без связи с финансами, кадровые новости без
технологического контекста, общественно-политические новости без влияния на финтех.

Отвечай строго JSON-массивом чисел в ТОМ ЖЕ ПОРЯДКЕ что и кейсы во входе."""


class DeepSeekProvider:
    def __init__(self, api_key: str, model: str = "deepseek-chat", timeout: int = 60):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            r = httpx.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                },
                timeout=15,
            )
            return r.status_code in (200, 400)
        except Exception as e:
            logger.warning(f"DeepSeek availability check failed: {e}")
            return False

    def _call(
        self,
        system: str,
        user: str,
        retry: int = 0,
        max_tokens: int = 1500,
        timeout: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        from time import perf_counter
        from llm.call_logger import log_llm_call

        effective_timeout = timeout or self.timeout
        prompt_chars = len(system) + len(user)
        start = perf_counter()
        response_content = ""
        usage: dict = {}
        success = True
        error_message = None

        try:
            payload: dict = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            }
            if reasoning_effort is not None:
                payload["reasoning_effort"] = reasoning_effort

            response = httpx.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=effective_timeout,
            )
            response.raise_for_status()
            data = response.json()

            usage = data.get("usage", {}) or {}
            if usage:
                cache_hit = usage.get("prompt_cache_hit_tokens", 0)
                cache_miss = usage.get("prompt_cache_miss_tokens", 0)
                completion = usage.get("completion_tokens", 0)
                total = usage.get("total_tokens", 0)
                cache_pct = (
                    int(cache_hit / (cache_hit + cache_miss) * 100)
                    if (cache_hit + cache_miss) > 0 else 0
                )
                logger.debug(
                    f"[tokens] cache_hit={cache_hit} cache_miss={cache_miss} "
                    f"completion={completion} total={total} cache={cache_pct}%"
                )
                if total > 500 and cache_pct == 0:
                    logger.warning(
                        f"[cache] 0% cache hit на {total} токенах — "
                        f"проверь структуру промпта (статика должна быть в начале system)"
                    )

            choice = data["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice.get("finish_reason", "")
            if not content:
                if finish_reason == "length":
                    reasoning_tokens = (
                        usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
                    )
                    raise ValueError(
                        f"Model exhausted max_tokens on reasoning ({reasoning_tokens} reasoning tokens) "
                        f"before producing content. Increase max_tokens for this call."
                    )
                raise ValueError("Empty response from DeepSeek API")
            response_content = content.strip()
            return response_content

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and retry < 2:
                success = False
                error_message = f"rate_limit (retry {retry + 1}/2)"
                wait = 30 * (retry + 1)
                logger.warning(f"DeepSeek rate limit, waiting {wait}s (retry {retry + 1}/2)")
                time.sleep(wait)
                return self._call(system, user, retry=retry + 1, max_tokens=max_tokens, timeout=timeout, reasoning_effort=reasoning_effort)
            if e.response.status_code == 401:
                logger.error("DeepSeek auth error: check DEEPSEEK_API_KEY")
            success = False
            error_message = str(e)[:500]
            raise

        except httpx.ReadTimeout:
            if retry < 2:
                success = False
                error_message = f"timeout (retry {retry + 1}/2)"
                logger.warning(f"DeepSeek timeout, retry {retry + 1}/2")
                time.sleep(5)
                return self._call(system, user, retry=retry + 1, max_tokens=max_tokens, timeout=timeout, reasoning_effort=reasoning_effort)
            success = False
            error_message = "ReadTimeout"
            raise

        except Exception as e:
            success = False
            error_message = str(e)[:500]
            raise

        finally:
            duration_ms = int((perf_counter() - start) * 1000)
            log_llm_call(
                provider="deepseek",
                model=self.model,
                prompt_chars=prompt_chars,
                response_chars=len(response_content),
                duration_ms=duration_ms,
                usage=usage,
                success=success,
                error_message=error_message,
            )

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
    # ОБЪЕДИНЁННЫЙ ВЫЗОВ 1+2 — Релевантность и классификация
    # ══════════════════════════════════════════════════════════════════════

    def check_relevance_and_classify(
        self, text: str, channel_context: str | None = None
    ) -> dict:
        """Объединённый вызов: релевантность + классификация. Экономит 1 LLM-вызов на пост."""
        channel_hint = f"Канал: {channel_context}\n\n" if channel_context else ""
        user = (
            f"{channel_hint}"
            f"Пост:\n{text}\n\n"
            f'Ответ JSON: {{"relevant": true/false, "relevance_reason": "кратко", '
            f'"type": "case"/"news"/"digest"/null, "case_count": 0}}'
        )
        raw = self._call(_RELEVANCE_SYSTEM, user, max_tokens=600)
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}
            return {
                "relevant": bool(data.get("relevant", False)),
                "relevance_reason": data.get("relevance_reason", ""),
                "type": data.get("type", "news"),
                "case_count": int(data.get("case_count", 0)),
                "classify_reason": data.get("classify_reason", ""),
            }
        except Exception as e:
            logger.warning(f"check_relevance_and_classify parse error: {e}")
            return {"relevant": False, "relevance_reason": "parse error",
                    "type": "news", "case_count": 0, "classify_reason": ""}

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
        """Извлекает структурированные данные кейсов из поста."""
        channel_hint = f"Канал: {channel_context}\n\n" if channel_context else ""
        user = (
            f"{channel_hint}"
            f"Пост:\n{text}\n\n"
            f"Извлеки кейсы. Ответ строго JSON-массив:\n"
            f'[{{"case_title": "...", "company": "...", "description": "...", '
            f'"how_it_works": "..." или null, "value": "...", '
            f'"market": "Россия"/"Мир"/"Россия и мир", "industry": "...", '
            f'"importance_score": 85}}]'
        )
        raw = self._call(_EXTRACT_CASES_SYSTEM, user, max_tokens=1800)
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
        trends_list = "\n".join(
            f"{t['id']}. {t['name']}"
            + (f" [{t.get('category','')}]" if t.get("category") else "")
            + (f" — {t.get('description','')[:80]}" if t.get("description") else "")
            for t in existing_trends
        )
        system = _ASSIGN_TREND_SYSTEM_TEMPLATE.format(trends_list=trends_list)

        user = (
            f"Кейс:\n"
            f"Название: {case.get('case_title', '')}\n"
            f"Компания: {case.get('company', '')}\n"
            f"Отрасль: {case.get('industry', '')}\n"
            f"Описание: {case.get('description', '')[:200]}\n"
            f"Ценность: {case.get('value', '')[:150]}\n\n"
            f'Ответ JSON: {{"decision": "existing"/"new"/"none", '
            f'"trend_id": число/null, "new_trend_name": null, '
            f'"new_trend_description": null, "reasoning": "кратко"}}'
        )

        raw = self._call(system, user, max_tokens=700)
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

    # ══════════════════════════════════════════════════════════════════════
    # Batch-переоценка importance_score
    # ══════════════════════════════════════════════════════════════════════

    def batch_score_importance(self, cases: list[dict]) -> list[int]:
        """
        Дешёвая batch-оценка importance_score для уже извлечённых кейсов.
        cases: список {"case_title", "company", "description"}.
        Возвращает список чисел той же длины и в том же порядке.
        """
        if not cases:
            return []

        cases_text = "\n".join(
            f"{i+1}. [{c.get('company', '—')}] {c.get('case_title', '')} — {(c.get('description') or '')[:150]}"
            for i, c in enumerate(cases)
        )
        user = (
            f"Оцени важность каждого кейса от 0 до 100 по описанным критериям.\n\n"
            f"Кейсы:\n{cases_text}\n\n"
            f'Ответ строго JSON: {{"scores": [число, число, ...]}}\n'
            f"Массив scores должен содержать ровно {len(cases)} чисел в том же порядке."
        )

        try:
            from llm.call_logger import llm_call_context
            with llm_call_context("batch_score_importance", context_note=f"backfill: {len(cases)} cases"):
                raw = self._call(_IMPORTANCE_BATCH_SYSTEM, user, max_tokens=400)
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(match.group()) if match else {}
            scores = data.get("scores", [])
            if len(scores) != len(cases):
                logger.warning(f"batch_score_importance: expected {len(cases)} scores, got {len(scores)}")
                scores = (scores + [50] * len(cases))[:len(cases)]
            return [max(0, min(100, int(s))) for s in scores]
        except Exception as e:
            logger.warning(f"batch_score_importance failed: {e}")
            return [50] * len(cases)
