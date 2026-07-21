"""Единый аналитический вызов для всего дайджеста."""
import json
import re

from loguru import logger


_DIGEST_ANALYSIS_SYSTEM = """Ты — аналитик финтех-дайджеста для банковских специалистов.
Пишешь по-русски в нейтральном аналитическом тоне: содержательно, с выводами и
связками между фактами, но без эмоциональных оценок и драматизации.

СТРОГИЕ ПРАВИЛА:
— Используй ТОЛЬКО факты из предоставленных кейсов. Не придумывай связи,
  тенденции или интерпретации, которые не следуют напрямую из текста кейсов.
— Не используй фразы уровня "экосистемный сдвиг", "новая парадигма",
  "трансформация отрасли" — это пустые обороты без содержания.
— Не используй оценочные усилители: "агрессивно", "стремительно", "взрывной рост",
  "прямой вызов", "не хочет упустить момент".
— Разрешены содержательные оценки основанные на фактах: "это говорит о том, что…",
  "это может означать…", "в отличие от X, здесь ставка на Y".
— Пиши как аналитик объясняющий коллеге суть происходящего, а не как
  пресс-релиз или новостная заметка.

ЗАДАЧИ (три в одном ответе):

1. ГЛАВНОЕ ЗА НЕДЕЛЮ — 1-2 абзаца связного текста (не список!) о 2-4
   самых значимых событиях недели. Показывай связи между кейсами если они
   реально есть (например несколько банков делают похожее), но не выдумывай
   связи которых нет в фактах.

2. ВЫВОД ПО КАЖДОЙ ТЕМЕ — одна короткая фраза (до 15 слов) отражающая
   суть того что происходит в теме на этой неделе. Не пересказ кейсов,
   а обобщение в одно предложение.

3. ВЕКТОРЫ ИЗМЕНЕНИЙ — 2-4 пункта, каждый 1-2 предложения. Это сквозные
   наблюдения которые пересекают несколько тем/кейсов — например если
   несколько разных компаний одновременно делают похожие шаги, или если
   видна общая закономерность (несколько кейсов о том что автоматизация
   без контроля человека даёт сбои). Если такого явного паттерна в данных
   недели нет — не выдумывай, дай меньше пунктов (1-2 честных наблюдения
   лучше чем 4 притянутых).

Отвечай строго JSON."""


def generate_digest_analysis(
    provider,
    top_cases: list[dict],
    topics: dict[str, list[dict]],
) -> dict:
    """Единый вызов: главное за неделю + выводы по темам + векторы изменений."""
    top_summary = "\n\n".join(
        f"[{c.get('trend_category', c.get('industry', 'Разное'))}] "
        f"{c.get('company', '—')}: {c.get('case_title', '')}\n"
        f"{c.get('description', '')[:200]}\n"
        f"Ценность: {c.get('value', '')[:150]}"
        for c in top_cases[:15]
    )

    topics_summary = []
    for topic, cases in topics.items():
        cases_short = "\n".join(
            f"- {c.get('company', '—')}: {c.get('case_title', '')}"
            for c in cases[:6]
        )
        topics_summary.append(f"ТЕМА: {topic}\n{cases_short}")
    topics_text = "\n\n".join(topics_summary)

    user = f"""НАИБОЛЕЕ ЗНАЧИМЫЕ КЕЙСЫ НЕДЕЛИ:
{top_summary}

ВСЕ ТЕМЫ И КЕЙСЫ НЕДЕЛИ:
{topics_text}

Ответ строго JSON:
{{
  "main_summary": "1-2 абзаца текста, разделённых \\n\\n",
  "topic_conclusions": {{
    "название темы 1": "короткий вывод до 15 слов",
    "название темы 2": "короткий вывод до 15 слов"
  }},
  "overall_conclusions": [
    "вектор изменений 1",
    "вектор изменений 2"
  ]
}}

Ключи в topic_conclusions должны ТОЧНО совпадать с названиями тем выше."""

    try:
        from llm.call_logger import llm_call_context
        with llm_call_context("generate_digest_analysis", context_note="digest"):
            raw = provider._call(_DIGEST_ANALYSIS_SYSTEM, user, max_tokens=1500)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}
        return {
            "main_summary": data.get("main_summary", ""),
            "topic_conclusions": data.get("topic_conclusions", {}),
            "overall_conclusions": data.get("overall_conclusions", []),
        }
    except Exception as e:
        logger.warning(f"generate_digest_analysis parse error: {e}")
        return {"main_summary": "", "topic_conclusions": {}, "overall_conclusions": []}


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
            raw = provider._call(_DYNAMICS_SYSTEM, user, max_tokens=800)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}
        return data.get("dynamics_points", [])
    except Exception as e:
        logger.warning(f"generate_dynamics_section parse error: {e}")
        return []
