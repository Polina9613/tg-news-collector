"""
Дедупликация кейсов дайджеста: republishing одного и того же события
разными Telegram-каналами со своей формулировкой заголовка.

Холистический LLM-проход по всему пулу кейсов периода — одним вызовом,
без пословного/company-string сравнения. Строковое сравнение company
(точное совпадение, пересечение множеств, нормализация суффиксов или
подстрок) ненадёжно: одна и та же компания в разных постах может быть
названа по-разному ("Сбер" / "ПАО Сбербанк", "Т-Банк" / "Тинькофф"), и
ни один из этих способов сравнения строк не покрывает все случаи — либо
пропускает реальные дубли, либо (при слишком широком сравнении вроде
подстрок) рискует ложно объединить разные компании с похожими именами.
LLM видит кейсы целиком и судит по смыслу, а не по написанию строки.

Работает один раз на уже отобранном для дайджеста пуле кейсов (после
фильтра importance_score, за конкретный период) — а не на растущем окне
при создании каждого кейса в enricher.
"""
from loguru import logger


def dedupe_cases(
    cases: list[dict], llm_call=None
) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """
    Один LLM-вызов на весь пул: llm_call("find_duplicate_groups", cases_payload)
    возвращает группы id кейсов, описывающих одно и то же реальное событие
    (та же компания и то же действие — независимо от точного написания
    названия компании или формулировки заголовка).

    Внутри каждой группы остаётся кейс с максимальным importance_score,
    остальные уходят в dropped_pairs. Кейсы, не попавшие ни в одну группу
    (включая кейсы без id), проходят как есть — не дубли.

    Если llm_call не передан, вызов упал с ошибкой, вернул пусто, или в
    пуле меньше двух сравнимых кейсов — группы не определяются, все кейсы
    считаются уникальными: лучше пропустить дубль, чем ошибочно объединить
    два разных факта в один.

    Возвращает (kept_cases, dropped_pairs):
      kept_cases — отфильтрованный список, сохраняет исходный относительный
        порядок cases.
      dropped_pairs — [(dropped_case, kept_case), ...] для опционального
        аудита (is_duplicate/duplicate_of_case_id в БД).
    """
    if not cases or llm_call is None:
        return cases, []

    by_id = {c["id"]: c for c in cases if c.get("id") is not None}
    if len(by_id) < 2:
        return cases, []

    cases_payload = [
        {
            "id": c["id"],
            "case_title": c.get("case_title"),
            "company": c.get("company"),
            "description": (c.get("description") or "")[:150],
        }
        for c in cases
        if c.get("id") is not None
    ]

    try:
        groups = llm_call("find_duplicate_groups", cases_payload)
    except Exception as e:
        logger.warning(f"find_duplicate_groups call failed, skipping dedup: {e}")
        return cases, []

    dropped_pairs: list[tuple[dict, dict]] = []
    dropped_ids: set = set()

    for group in groups or []:
        group_ids = [gid for gid in group if gid in by_id and gid not in dropped_ids]
        if len(group_ids) < 2:
            continue
        group_cases = [by_id[gid] for gid in group_ids]
        kept = max(group_cases, key=lambda c: c.get("importance_score", 50))
        for c in group_cases:
            if c is kept:
                continue
            dropped_pairs.append((c, kept))
            dropped_ids.add(c["id"])
            logger.debug(
                f"Digest dedup (LLM): '{c.get('case_title')}' ~ '{kept.get('case_title')}' — dropped"
            )

    kept_cases = [c for c in cases if c.get("id") not in dropped_ids]
    logger.info(
        f"Digest dedup: 1 LLM call, {len(groups or [])} group(s) returned, "
        f"{len(dropped_pairs)} duplicate(s) dropped"
    )
    return kept_cases, dropped_pairs
