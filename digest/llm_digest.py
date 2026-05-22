import json
import re

from loguru import logger


def get_top5(provider, cases: list[dict]) -> list[dict]:
    system = (
        "Ты — аналитик финтех-рынка. "
        "Пишешь для коллег-аналитиков которые профессионально следят за трендами."
    )
    user = f"""Выбери 5 самых значимых новостей за период.
Критерии: технологические прорывы, крупные запуски продуктов,
регуляторные изменения, значимые сделки, новые бизнес-модели.

Для каждой новости:
- title: конкретный заголовок с названием компании и сутью
- summary: 2-3 предложения — кто, что сделал, конкретные цифры если есть,
  что это означает для рынка
- source: название источника
- url: ссылка

Пиши плотно: факты, цифры, рыночный контекст. Не объясняй термины.

Новости:
{_format_cases(cases)}

Ответь строго JSON-массивом из 5 объектов. Только JSON."""
    raw = provider._call(system, user)
    return _parse_list(raw)


def get_topic_intro(provider, topic: str, cases: list[dict]) -> str:
    system = (
        "Ты — аналитик финтех-рынка. "
        "Пишешь для профессиональной аудитории."
    )
    user = f"""Напиши вводный абзац раздела «{topic}» (3-4 предложения).
Опиши тенденцию: что происходит в этой области прямо сейчас,
куда движется рынок, какие игроки активны.
Используй конкретику из кейсов — компании, цифры, технологии.
Не объясняй базовые понятия.

Кейсы:
{_format_cases(cases)}

Только текст абзаца, без заголовков и пояснений."""
    return provider._call(system, user)


def get_facts(provider, cases: list[dict]) -> list[dict]:
    system = "Ты — аналитик финтех-рынка."
    user = f"""Извлеки числовые факты из кейсов:
объёмы рынков, доли, суммы, количество пользователей,
даты запуска, темпы роста, конверсии.
Только то что явно написано в текстах.
Максимум 12 фактов. Сортируй от наиболее впечатляющих.

Кейсы:
{_format_cases(cases)}

Ответь строго JSON-массивом: [{{"fact": "...", "context": "..."}}]. Только JSON."""
    raw = provider._call(system, user)
    return _parse_list(raw)


def _format_cases(cases: list[dict]) -> str:
    lines = []
    for i, c in enumerate(cases, 1):
        lines.append(f"{i}. {c.get('case_title', 'Без названия')} [{c.get('source_title', '')}]")
        if c.get("description"):
            lines.append(f"   {c['description']}")
        if c.get("value"):
            lines.append(f"   Ценность: {c['value']}")
        if c.get("source_url"):
            lines.append(f"   Ссылка: {c['source_url']}")
        lines.append("")
    return "\n".join(lines)


def _parse_list(raw: str) -> list:
    try:
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        return json.loads(match.group()) if match else []
    except Exception as e:
        logger.warning(f"LLM parse error: {e} | raw: {raw[:200]}")
        return []
