"""Аналитические LLM-вызовы для дайджеста."""
import json
import re

from loguru import logger


_MAIN_SUMMARY_SYSTEM = """Ты — аналитик финтех-дайджеста для банковских специалистов.
Пишешь по-русски в нейтральном аналитическом тоне: содержательно, с выводами и
связками между фактами, но без эмоциональных оценок и драматизации.

СТРОГИЕ ПРАВИЛА:
— Используй ТОЛЬКО факты из предоставленных кейсов.
— Не используй пустые обороты: "экосистемный сдвиг", "новая парадигма".
— Не используй усилители: "агрессивно", "взрывной рост", "прямой вызов".
— Разрешены содержательные оценки: "это говорит о том, что…".

ЗАДАЧА: напиши 1-2 абзаца (main_summary) о 2-4 самых значимых событиях недели
на основе предоставленных кейсов. Показывай связи между кейсами если они
реально есть, но не выдумывай.

Отвечай строго JSON."""


def generate_main_summary(provider, top_cases: list[dict]) -> str:
    """Генерирует только 'Главное за неделю' — лёгкий вызов, малый контекст."""
    top_summary = "\n\n".join(
        f"[{c.get('trend_category', c.get('industry', 'Разное'))}] "
        f"{c.get('company', '—')}: {c.get('case_title', '')}\n"
        f"{c.get('description', '')[:150]}\n"
        f"Ценность: {c.get('value', '')[:100]}"
        for c in top_cases[:10]
    )

    user = f"""НАИБОЛЕЕ ЗНАЧИМЫЕ КЕЙСЫ НЕДЕЛИ:
{top_summary}

Ответ строго JSON:
{{"main_summary": "1-2 абзаца текста, разделённых \\n\\n"}}"""

    try:
        from llm.call_logger import llm_call_context
        with llm_call_context("generate_main_summary", context_note="digest"):
            raw = provider._call(_MAIN_SUMMARY_SYSTEM, user, max_tokens=1000, timeout=90)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}
        return data.get("main_summary", "")
    except Exception as e:
        logger.warning(f"generate_main_summary parse error: {e}")
        return ""


_TOPIC_ANALYSIS_SYSTEM = """Ты — аналитик финтех-дайджеста.
Пишешь по-русски просто и по делу, без канцелярита и пустых оборотов.

ЗАДАЧИ:
1. Для каждой темы — короткий вывод (до 15 слов) что происходит в теме на этой неделе.
2. 2-4 вектора изменений — сквозные наблюдения пересекающие несколько тем/кейсов.
   Если явного паттерна нет — дай меньше пунктов, не выдумывай.

Отвечай строго JSON."""


def generate_topic_analysis(
    provider,
    topics: dict[str, list[dict]],
) -> dict:
    """Генерирует topic_conclusions + overall_conclusions — отдельно от main_summary."""
    topics_summary = []
    for topic, cases in topics.items():
        cases_short = "\n".join(
            f"- {c.get('company', '—')}: {c.get('case_title', '')}"
            for c in cases[:5]
        )
        topics_summary.append(f"ТЕМА: {topic}\n{cases_short}")
    topics_text = "\n\n".join(topics_summary)

    user = f"""ТЕМЫ И КЕЙСЫ НЕДЕЛИ:
{topics_text}

Ответ строго JSON:
{{
  "topic_conclusions": {{"название темы": "короткий вывод до 15 слов"}},
  "overall_conclusions": ["вектор изменений 1", "вектор изменений 2"]
}}

Ключи в topic_conclusions должны ТОЧНО совпадать с названиями тем выше."""

    try:
        from llm.call_logger import llm_call_context
        with llm_call_context("generate_topic_analysis", context_note="digest"):
            raw = provider._call(_TOPIC_ANALYSIS_SYSTEM, user, max_tokens=1600, timeout=120)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}
        return {
            "topic_conclusions": data.get("topic_conclusions", {}),
            "overall_conclusions": data.get("overall_conclusions", []),
        }
    except Exception as e:
        logger.warning(f"generate_topic_analysis parse error: {e}")
        return {"topic_conclusions": {}, "overall_conclusions": []}


_DYNAMICS_SYSTEM = """Ты — аналитик, который следит за финтех-новостями каждую неделю
и объясняет коллеге, что изменилось за последний месяц. Пиши просто, как будто
рассказываешь за чашкой кофе — короткими предложениями, без канцелярита и сложных слов.

ЗАПРЕЩЕНО:
— Канцелярские обороты: "представлена кейсом", "получила подтверждение",
  "продемонстрировала рост", "было зафиксировано"
— Наукообразные метафоры: "прошла путь от", "перешла в стадию", "экосистемный сдвиг"
— Общие фразы без цифр: "заметен рост интереса", "тема набирает популярность"

МОЖНО И НУЖНО:
— Конкретные цифры: "было 3, стало 5", "неделю назад один кейс, сейчас четыре"
— Простые связки: "и вот", "а сейчас", "к ним подключился"
— Называть компании по именам, а не обобщённо

ЗАДАЧА: сравни компании и темы текущей недели с прошлыми неделями.
Ищи ТОЛЬКО реальные пересечения — одна и та же компания или тема встречается
несколько недель подряд. Если пересечений нет — не выдумывай, лучше меньше пунктов.
Если что-то было активно раньше, а на этой неделе пропало — тоже можно упомянуть,
одной короткой фразой.

Выбери 2-4 самых заметных изменения. Каждое — 2-4 предложения.
Отвечай строго JSON."""


def generate_dynamics_section(
    provider,
    current_index: list[dict],
    current_conclusions: list[str],
    past_snapshots: list[dict],
) -> list[str]:
    """
    Генерирует раздел "Динамика за месяц" — сравнение текущей недели с прошлыми.

    past_snapshots — список словарей: period_label, compact_case_index, overall_conclusions.
    Возвращает список пунктов (может быть пустым если пересечений нет).
    """
    if not past_snapshots:
        return []

    past_text_parts = []
    for snap in past_snapshots:
        cases_summary = "; ".join(
            f"{c['company']} — {c['title']}" for c in snap["compact_case_index"][:20]
        )
        past_text_parts.append(
            f"Неделя {snap['period_label']}:\n"
            f"Кейсы: {cases_summary}\n"
            f"Выводы: {'; '.join(snap['overall_conclusions'])}"
        )
    past_text = "\n\n".join(past_text_parts)

    current_summary = "; ".join(
        f"{c['company']} — {c['title']}" for c in current_index[:20]
    )

    user = f"""ПРОШЛЫЕ НЕДЕЛИ:
{past_text}

ТЕКУЩАЯ НЕДЕЛЯ:
Кейсы: {current_summary}
Выводы: {'; '.join(current_conclusions)}

Сравни и найди реальные пересечения по компаниям/темам.

Ответ строго JSON:
{{"dynamics_points": ["пункт 1", "пункт 2"]}}"""

    try:
        from llm.call_logger import llm_call_context
        with llm_call_context("generate_dynamics_section", context_note="digest_dynamics"):
            raw = provider._call(_DYNAMICS_SYSTEM, user, max_tokens=1500, timeout=120)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}
        return data.get("dynamics_points", [])
    except Exception as e:
        logger.warning(f"generate_dynamics_section parse error: {e}")
        return []
