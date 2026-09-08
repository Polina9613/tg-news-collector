"""
Дедупликация кейсов дайджеста: republishing одного и того же события
разными Telegram-каналами со своей формулировкой заголовка.

Работает один раз на уже отобранном для дайджеста пуле кейсов (после
фильтра importance_score, за конкретный период) — а не на растущем окне
при создании каждого кейса в enricher. Так дешевле (маленький пул сравнений
вместо скользящего окна по всей истории) и проще отлаживать: один явный шаг
перед сборкой документа, а не логика размазанная по фоновому enrich-процессу.
"""
from loguru import logger
from rapidfuzz import fuzz

DUPLICATE_TITLE_FUZZY_THRESHOLD = 70  # rapidfuzz.token_set_ratio, 0-100 — однозначный дубль
DUPLICATE_TITLE_FUZZY_LLM_MIN = 40    # ниже этого — однозначно разные события, LLM не спрашиваем
DUPLICATE_LLM_MAX_CANDIDATES = 5      # не более N кандидатов в одном LLM-запросе


def dedupe_cases(
    cases: list[dict], llm_call=None
) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """
    Группирует кейсы по company, внутри группы сравнивает case_title
    (rapidfuzz.token_set_ratio):
      >= DUPLICATE_TITLE_FUZZY_THRESHOLD — однозначный дубль, без LLM.
         Ловит republishing одного события разными каналами с разной
         формулировкой заголовка — точное совпадение слов для этого не
         годится, т.к. пересказ обычно использует другие слова.
      [DUPLICATE_TITLE_FUZZY_LLM_MIN, DUPLICATE_TITLE_FUZZY_THRESHOLD) —
         просим LLM рассудить через llm_call("check_duplicate_llm", new_case,
         candidates). Чисто лексическое сравнение не может надёжно отличить
         "тот же факт другими словами" от "другое событие с частично похожим
         набором слов" — эти случаи неразличимы по одному числу.
      < DUPLICATE_TITLE_FUZZY_LLM_MIN — однозначно разные события, не сравниваем.

    Кейсы без company или без case_title сравнению не подлежат (сравнивать
    не с чем) и всегда остаются в выдаче.

    Группа обрабатывается в порядке убывания importance_score, поэтому в
    кластере дублей выживает кейс с наивысшим importance_score — он попадает
    в reps первым и становится "оригиналом", с которым сравниваются остальные.

    Возвращает (kept_cases, dropped_pairs):
      kept_cases — отфильтрованный список, сохраняет исходный относительный
        порядок cases.
      dropped_pairs — [(dropped_case, kept_case), ...] для опционального
        аудита (is_duplicate/duplicate_of_case_id в БД).
    """
    if not cases:
        return cases, []

    groups: dict[str, list[dict]] = {}
    keep_ids: set[int] = set()
    for c in cases:
        company = c.get("company")
        title = c.get("case_title")
        if not company or not title:
            keep_ids.add(id(c))
            continue
        groups.setdefault(company, []).append(c)

    dropped_pairs: list[tuple[dict, dict]] = []

    for company, group in groups.items():
        if len(group) == 1:
            keep_ids.add(id(group[0]))
            continue

        ordered = sorted(group, key=lambda c: c.get("importance_score", 50), reverse=True)
        reps: list[dict] = []

        for case in ordered:
            title = case["case_title"]
            dup_rep = None
            borderline: list[tuple[dict, float]] = []

            for rep in reps:
                score = fuzz.token_set_ratio(title, rep["case_title"])
                if score >= DUPLICATE_TITLE_FUZZY_THRESHOLD:
                    dup_rep = rep
                    logger.debug(
                        f"Digest dedup (fuzzy): '{title}' ~ '{rep['case_title']}' ({score:.0f}) — dropped"
                    )
                    break
                if score >= DUPLICATE_TITLE_FUZZY_LLM_MIN:
                    borderline.append((rep, score))

            if dup_rep is None and borderline and llm_call is not None:
                borderline.sort(key=lambda x: -x[1])
                candidates_batch = borderline[:DUPLICATE_LLM_MAX_CANDIDATES]
                candidates_payload = [
                    {
                        "id": rep.get("id"),
                        "case_title": rep["case_title"],
                        "description": rep.get("description"),
                    }
                    for rep, _ in candidates_batch
                ]
                try:
                    dup_id = llm_call(
                        "check_duplicate_llm",
                        {"case_title": title, "description": case.get("description")},
                        candidates_payload,
                    )
                except Exception as e:
                    logger.warning(f"check_duplicate_llm call failed, skipping: {e}")
                    dup_id = None

                if dup_id is not None:
                    valid_ids = {rep.get("id") for rep, _ in candidates_batch}
                    if dup_id in valid_ids:
                        dup_rep = next(rep for rep, _ in candidates_batch if rep.get("id") == dup_id)
                        logger.debug(
                            f"Digest dedup (LLM): '{title}' ~ '{dup_rep['case_title']}' — dropped"
                        )
                    else:
                        logger.warning(
                            f"check_duplicate_llm returned id {dup_id} outside candidates, ignoring"
                        )

            if dup_rep is not None:
                dropped_pairs.append((case, dup_rep))
                continue

            reps.append(case)
            keep_ids.add(id(case))

    kept_cases = [c for c in cases if id(c) in keep_ids]
    return kept_cases, dropped_pairs
