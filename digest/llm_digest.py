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

ЗАДАЧА: раздели предоставленные кейсы (топ по важности недели) на 3-5
смысловых мини-кластеров — сгруппируй по общей сути (одна компания,
одна тема, один тип технологии), а не бери кейсы по одному.
Для каждого кластера напиши:
— intro: одно вводное предложение, называющее суть кластера.
— bullets: 1-3 буллета по кейсам этого кластера. Каждый буллет —
  конкретный факт из кейса + связка причины или значимости
  ("...что указывает на...", "...что говорит о...", "...на фоне..."),
  а не просто пересказ факта без вывода.

Если кейсов мало или они разнородны — можно сформировать меньше
кластеров (но не меньше 2). Не выдумывай факты и связи, которых нет
в предоставленных кейсах.

Отвечай строго JSON:
{"main_summary_clusters": [{"intro": "...", "bullets": ["...", "..."]}]}"""


def generate_main_summary(provider, top_cases: list[dict]) -> list[dict]:
    """
    Генерирует 'Главное за неделю' как 3-5 мини-кластеров {intro, bullets} —
    лёгкий вызов, малый контекст. Источник данных — топ кейсов по
    importance_score, независимо от _group_by_topic (не пересекается с
    группировкой "Новости по темам").
    """
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
{{"main_summary_clusters": [{{"intro": "...", "bullets": ["...", "..."]}}]}}"""

    try:
        from llm.call_logger import llm_call_context
        with llm_call_context("generate_main_summary", context_note="digest"):
            raw = provider._call(_MAIN_SUMMARY_SYSTEM, user, max_tokens=1200, timeout=90)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}
        clusters = data.get("main_summary_clusters", [])
        if not isinstance(clusters, list):
            return []
        return [
            {"intro": c.get("intro") or "", "bullets": c.get("bullets") or []}
            for c in clusters
            if isinstance(c, dict)
        ]
    except Exception as e:
        logger.warning(f"generate_main_summary parse error: {e}")
        return []


_TOPIC_ANALYSIS_SYSTEM = """Ты — аналитик финтех-дайджеста.
Пишешь по-русски просто и по делу, без канцелярита и пустых оборотов.

ЗАДАЧИ:
1. Для каждой темы — короткий вывод (до 15 слов) что происходит в теме на этой неделе.
2. 5-6 векторов изменений — сквозные наблюдения пересекающие несколько тем/кейсов.
   НЕ пиши по одному выводу на тему — ищи связи МЕЖДУ темами, а не пересказ
   отдельной темы. Если явного паттерна нет — дай меньше пунктов, не выдумывай;
   лучше 3 содержательных вывода, чем 6 натянутых.

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
и объясняет коллеге, что изменилось за последние несколько недель. Пиши просто,
как будто рассказываешь за чашкой кофе — короткими предложениями, без канцелярита.

ВАЖНО: тебе показан период сравнения — конкретное количество недель (может быть
от 1 до 5). Если факт встречался в показанных данных — упоминай это как факт.
Если факта НЕТ ни в одном из показанных снимков — НЕ утверждай что "тема не
поднималась раньше" или "это новое направление". Вместо этого просто не упоминай
отсутствие темы, либо скажи нейтрально "за последние N недель эта тема не звучала"
(используй реальное число недель которое тебе показано).

ЗАПРЕЩЕНО:
— Канцелярские обороты, наукообразные метафоры, общие фразы без цифр
— Утверждения "впервые", "новое направление", "раньше не было" —
  если ты не уверена что это действительно так для ВСЕГО показанного периода

МОЖНО И НУЖНО:
— Конкретные цифры: "было 3, стало 5"
— Явно указывать охват: "за последние 3 недели" вместо "ранее"
— Называть компании по именам

ЗАДАЧА: сравни компании и темы текущей недели с показанными прошлыми неделями.
Ищи ТОЛЬКО реальные пересечения. Если пересечений нет — не выдумывай, меньше пунктов — лучше.

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

    weeks_covered = len(past_snapshots)

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

    user = f"""Тебе показаны данные за последние {weeks_covered} недель (не больше).

ПРОШЛЫЕ НЕДЕЛИ ({weeks_covered}):
{past_text}

ТЕКУЩАЯ НЕДЕЛЯ:
Кейсы: {current_summary}
Выводы: {'; '.join(current_conclusions)}

Сравни и найди реальные пересечения по компаниям/темам.
Если упоминаешь что тема не поднималась раньше — уточняй "за последние {weeks_covered} недель".

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
