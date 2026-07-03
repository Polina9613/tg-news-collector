"""Промпты для генерации research-документа по теме."""
import json
import re


_TOPIC_TO_TRENDS_SYSTEM = """Ты — методолог трендвотчинга в финтех-исследовании.
Определяешь какие из канонических трендов относятся к свободному запросу аналитика.

СПИСОК ТРЕНДОВ:
{trends_list}

Отвечай строго JSON. Возвращай ТОЛЬКО id трендов явно относящихся к запросу.
Если запрос узкий — может быть 1 тренд. Если запрос широкий — несколько.
Если запрос не соответствует ни одному тренду — верни пустой список."""


def resolve_query_to_trends(provider, query: str, all_trends: list[dict]) -> list[int]:
    """Переводит свободный текстовый запрос в список релевантных trend_id."""
    trends_list = "\n".join(f"{t['id']}. {t['name']}" for t in all_trends)
    system = _TOPIC_TO_TRENDS_SYSTEM.format(trends_list=trends_list)
    user = f'Запрос аналитика: "{query}"\n\nОтвет JSON: {{"trend_ids": [список чисел]}}'

    raw = provider._call(system, user, max_tokens=100)
    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}
        return [int(x) for x in data.get("trend_ids", [])]
    except Exception:
        return []


_RESEARCH_SYNTHESIS_SYSTEM = """Ты — аналитик трендвотчинга в крупном российском банке.
Пишешь структурированное исследование по теме на основе накопленных кейсов.

Стиль: деловой, конкретный, без воды. Фокус на технологиях и практической сути,
а не на общих рассуждениях. Каждое утверждение опирается на конкретные кейсы.

СТРУКТУРА ДОКУМЕНТА:
1. Что происходит — краткий обзор темы (3-4 предложения)
2. Технологии и подходы — как это работает технически, что общего у решений,
   какие есть вариации подходов
3. Кто и как реализует — ключевые компании и что именно они сделали
   (не просто список, а что отличает подходы друг от друга)
4. Выводы — куда движется тема, что это значит для банка, на что обратить внимание

Отвечай строго JSON с четырьмя полями."""


def generate_research_synthesis(provider, query: str, cases: list[dict]) -> dict:
    """Синтезирует research-документ из отобранных кейсов."""
    cases_text = "\n\n".join(
        f"Кейс {i+1} [{c.get('trend_name', '—')}]\n"
        f"Компания: {c.get('company', '—')}\n"
        f"Заголовок: {c.get('case_title', '')}\n"
        f"Описание: {c.get('description', '')}\n"
        f"Как работает: {c.get('how_it_works') or '—'}\n"
        f"Ценность: {c.get('value', '')}\n"
        f"Рынок: {c.get('market', '—')}"
        for i, c in enumerate(cases)
    )

    system = _RESEARCH_SYNTHESIS_SYSTEM
    user = (
        f'Тема исследования: "{query}"\n\n'
        f"Кейсы из базы знаний ({len(cases)} шт.):\n\n{cases_text}\n\n"
        f'Ответ строго JSON: {{"overview": "...", "technology": "...", '
        f'"players": "...", "conclusions": "..."}}'
    )

    raw = provider._call(system, user, max_tokens=2000)
    try:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}
        return {
            "overview": data.get("overview", ""),
            "technology": data.get("technology", ""),
            "players": data.get("players", ""),
            "conclusions": data.get("conclusions", ""),
        }
    except Exception as e:
        from loguru import logger
        logger.warning(f"generate_research_synthesis parse error: {e}")
        return {"overview": "Ошибка генерации", "technology": "", "players": "", "conclusions": ""}
