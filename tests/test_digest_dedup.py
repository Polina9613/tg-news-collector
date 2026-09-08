"""
Tests: digest/dedup.py — дедупликация republishing-кейсов внутри финального
пула дайджеста (после фильтра importance_score, за конкретный период).

Примеры (real + синтетические негативы) — из дайджеста 1-8 сентября, где
эти заголовки создали кратные копии одного и того же факта.
"""
from digest.dedup import dedupe_cases


def _case(id_, company, case_title, importance_score=50, description="d"):
    return {
        "id": id_,
        "company": company,
        "case_title": case_title,
        "description": description,
        "importance_score": importance_score,
    }


# ── Без LLM (llm_call=None) — только явные fuzzy-дубли (>=70) ─────────────────

def test_exact_fuzzy_duplicate_dropped_without_llm():
    """ВТБ: fuzzy=89.4 — выше порога 70, ловится без LLM."""
    cases = [
        _case(1, "ВТБ", "ВТБ запускает детский банк", importance_score=80),
        _case(2, "ВТБ", "ВТБ запускает детский онлайн-банк с поэтапным расширением самостоятельности", importance_score=70),
    ]
    kept, dropped = dedupe_cases(cases, llm_call=None)
    assert [c["id"] for c in kept] == [1]
    assert len(dropped) == 1
    assert dropped[0][0]["id"] == 2
    assert dropped[0][1]["id"] == 1


def test_highest_importance_survives_in_cluster():
    """Из кластера дублей выживает кейс с наивысшим importance_score,
    даже если он не первый в исходном списке."""
    cases = [
        _case(1, "ВТБ", "ВТБ запускает детский банк", importance_score=60),
        _case(2, "ВТБ", "ВТБ запускает детский онлайн-банк с поэтапным расширением самостоятельности", importance_score=95),
    ]
    kept, dropped = dedupe_cases(cases, llm_call=None)
    assert [c["id"] for c in kept] == [2]
    assert dropped[0][0]["id"] == 1
    assert dropped[0][1]["id"] == 2


def test_below_llm_fallback_min_not_compared_at_all():
    """fuzzy < 40 — однозначно разные события, даже без llm_call ничего не ловится
    (и не должно: это ожидаемое поведение, не false negative)."""
    cases = [
        _case(1, "ВТБ", "ВТБ запускает детский банк", importance_score=80),
        _case(2, "ВТБ", "ВТБ повысил ставку по вкладам до 18 процентов годовых", importance_score=70),
    ]
    kept, dropped = dedupe_cases(cases, llm_call=None)
    assert {c["id"] for c in kept} == {1, 2}
    assert dropped == []


def test_borderline_without_llm_call_not_dropped():
    """fuzzy в серой зоне [40,70), но llm_call не передан — кейс не удаляется
    (безопасный дефолт: не потерять данные молча)."""
    cases = [
        _case(1, "Альфа-Банк", "Альфа-Банк и Beeline Cloud создали гибридную ИИ-инфраструктуру", importance_score=80),
        _case(2, "Альфа-Банк", "Альфа-Банк развернул ИИ-платформу на мощностях Beeline Cloud", importance_score=70),
    ]
    kept, dropped = dedupe_cases(cases, llm_call=None)
    assert {c["id"] for c in kept} == {1, 2}
    assert dropped == []


def test_different_company_never_compared():
    cases = [
        _case(1, "Сбер", "Сбер запустил крипторасчеты для бизнеса", importance_score=80),
        _case(2, "ВТБ", "ВТБ запустил крипторасчеты для бизнеса", importance_score=70),
    ]
    kept, dropped = dedupe_cases(cases, llm_call=None)
    assert {c["id"] for c in kept} == {1, 2}
    assert dropped == []


def test_case_without_company_or_title_passes_through():
    cases = [
        _case(1, None, "Некая новость без компании", importance_score=80),
        _case(2, "Сбер", None, importance_score=70),
    ]
    cases[1]["case_title"] = None
    kept, _ = dedupe_cases(cases, llm_call=None)
    assert {c["id"] for c in kept} == {1, 2}


def test_empty_list():
    kept, dropped = dedupe_cases([], llm_call=None)
    assert kept == []
    assert dropped == []


# ── С LLM-fallback (серая зона [40, 70)) ───────────────────────────────────────

def _make_llm_call(verdicts: dict[str, int | None]):
    """verdicts: {new_case_title: id_кандидата_или_None}."""
    def _call(method_name, new_case, candidates):
        assert method_name == "check_duplicate_llm"
        return verdicts.get(new_case["case_title"])
    return _call


def test_alfa_borderline_pair_confirmed_by_llm():
    """Alfa: fuzzy=62.3, в серой зоне — без LLM не поймать, с LLM ловится."""
    kept_title = "Альфа-Банк и Beeline Cloud создали гибридную ИИ-инфраструктуру"
    dropped_title = "Альфа-Банк развернул ИИ-платформу на мощностях Beeline Cloud"
    cases = [
        _case(1, "Альфа-Банк", kept_title, importance_score=80),
        _case(2, "Альфа-Банк", dropped_title, importance_score=70),
    ]
    llm_call = _make_llm_call({dropped_title: 1})
    kept, dropped = dedupe_cases(cases, llm_call=llm_call)
    assert [c["id"] for c in kept] == [1]
    assert dropped[0][0]["id"] == 2


def test_sber_four_titles_collapse_to_one():
    """Все 4 реальных заголовка про крипторасчёты Сбера должны схлопнуться
    в один кейс — ровно тот баг, что был в дайджесте 1-8 сентября."""
    titles = [
        "Сбер запускает криптоплатежи для международных расчётов корпоративных клиентов",
        "Сбер запускает международные расчёты в криптовалюте",
        "Сбер запустил крипторасчеты для бизнеса",
        "Сбер открыл трансграничные расчеты в криптовалюте для корпоративных клиентов",
    ]
    # importance_score по убыванию — первый в titles должен выжить
    cases = [_case(i + 1, "Сбер", t, importance_score=90 - i) for i, t in enumerate(titles)]

    # LLM: любой заголовок про крипту/расчёты — дубль первого кандидата в списке
    def llm_call(method_name, new_case, candidates):
        assert method_name == "check_duplicate_llm"
        return candidates[0]["id"] if candidates else None

    kept, dropped = dedupe_cases(cases, llm_call=llm_call)
    assert [c["id"] for c in kept] == [1]
    assert len(dropped) == 3


def test_llm_rejects_different_event_same_company():
    """Негатив: 'крипторасчеты для бизнеса' vs 'мобильный офис для бизнеса' —
    fuzzy=58.2 (серая зона), но разные события. LLM отклоняет объединение."""
    kept_title = "Сбер запустил крипторасчеты для бизнеса"
    other_title = "Сбер представил новый мобильный офис для малого бизнеса в регионах"
    cases = [
        _case(1, "Сбер", kept_title, importance_score=80),
        _case(2, "Сбер", other_title, importance_score=70),
    ]
    llm_call = _make_llm_call({other_title: None})  # LLM говорит "другое событие"
    kept, dropped = dedupe_cases(cases, llm_call=llm_call)
    assert {c["id"] for c in kept} == {1, 2}
    assert dropped == []


def test_llm_call_exception_falls_back_to_keep():
    """Если LLM-вызов падает — не должно ломать генерацию дайджеста,
    кейс остаётся (безопасный откат — не потерять данные)."""
    kept_title = "Альфа-Банк и Beeline Cloud создали гибридную ИИ-инфраструктуру"
    dropped_title = "Альфа-Банк развернул ИИ-платформу на мощностях Beeline Cloud"
    cases = [
        _case(1, "Альфа-Банк", kept_title, importance_score=80),
        _case(2, "Альфа-Банк", dropped_title, importance_score=70),
    ]

    def _failing_llm_call(*args, **kwargs):
        raise RuntimeError("LLM недоступен")

    kept, dropped = dedupe_cases(cases, llm_call=_failing_llm_call)
    assert {c["id"] for c in kept} == {1, 2}
    assert dropped == []


def test_llm_returns_id_outside_candidates_is_ignored():
    kept_title = "Альфа-Банк и Beeline Cloud создали гибридную ИИ-инфраструктуру"
    dropped_title = "Альфа-Банк развернул ИИ-платформу на мощностях Beeline Cloud"
    cases = [
        _case(1, "Альфа-Банк", kept_title, importance_score=80),
        _case(2, "Альфа-Банк", dropped_title, importance_score=70),
    ]
    llm_call = _make_llm_call({dropped_title: 999999})  # id не из кандидатов
    kept, dropped = dedupe_cases(cases, llm_call=llm_call)
    assert {c["id"] for c in kept} == {1, 2}
    assert dropped == []


def test_dropped_pairs_reference_correct_kept_case():
    """dropped_pairs должны содержать правильную пару (dropped, kept) для
    последующей записи duplicate_of_case_id в БД."""
    cases = [
        _case(1, "ВТБ", "ВТБ запускает детский банк", importance_score=80),
        _case(2, "ВТБ", "ВТБ запускает детский онлайн-банк с поэтапным расширением самостоятельности", importance_score=70),
    ]
    _, dropped = dedupe_cases(cases, llm_call=None)
    assert len(dropped) == 1
    dropped_case, kept_case = dropped[0]
    assert dropped_case["id"] == 2
    assert kept_case["id"] == 1
