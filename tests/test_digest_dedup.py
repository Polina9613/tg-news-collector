"""
Тесты digest.dedup.dedupe_cases — холистический LLM-проход по всему пулу.

llm_call в тестах — стаб с сигнатурой llm_call(method_name, cases_payload),
имитирующий digest/generator.py's _llm_call(method_name, *args, **kwargs) ->
getattr(provider, method_name)(*args, **kwargs), т.е. provider.find_duplicate_groups(cases).
"""
from digest.dedup import dedupe_cases


def _case(id_, case_title, company, importance=50, description=""):
    return {
        "id": id_,
        "case_title": case_title,
        "company": company,
        "importance_score": importance,
        "description": description,
    }


def test_empty_input_returns_empty():
    kept, dropped = dedupe_cases([])
    assert kept == []
    assert dropped == []


def test_no_llm_call_kept_unchanged_no_dedup_attempted():
    """Без llm_call дедуп не выполняется вовсе — безопасный дефолт."""
    cases = [
        _case(1, "Кейс A", "A"),
        _case(2, "Кейс B", "B"),
    ]
    kept, dropped = dedupe_cases(cases, llm_call=None)
    assert kept == cases
    assert dropped == []


def test_single_comparable_case_llm_not_called():
    """Меньше двух кейсов с id — сравнивать не с чем, LLM не вызывается."""
    cases = [_case(1, "Единственный кейс", "A")]

    def llm_call(*args, **kwargs):
        raise AssertionError("LLM should not be called with fewer than 2 comparable cases")

    kept, dropped = dedupe_cases(cases, llm_call=llm_call)
    assert kept == cases
    assert dropped == []


def test_sber_pao_sberbank_grouped_despite_different_company_strings():
    """Регрессионный тест: company='Сбер' vs 'ПАО Сбербанк' — разные строки,
    не пересекаются, поэтому пословное/company-gated сравнение их не ловило.
    Холистический LLM-проход видит обе компании в одном запросе и решает
    по смыслу, независимо от точного написания строки."""
    high = _case(1, "Сбер запустил крипторасчеты для бизнеса", "Сбер", importance=95)
    low = _case(2, "ПАО Сбербанк объявило о запуске расчётов в криптовалюте", "ПАО Сбербанк", importance=70)

    def llm_call(method_name, cases_payload):
        assert method_name == "find_duplicate_groups"
        ids = {c["id"] for c in cases_payload}
        assert ids == {1, 2}
        return [[1, 2]]

    kept, dropped = dedupe_cases([high, low], llm_call=llm_call)

    assert kept == [high]
    assert dropped == [(low, high)]


def test_llm_returns_no_groups_all_kept():
    cases = [
        _case(1, "Кейс A", "A", importance=80),
        _case(2, "Кейс B", "B", importance=60),
    ]

    def llm_call(method_name, cases_payload):
        return []

    kept, dropped = dedupe_cases(cases, llm_call=llm_call)
    assert kept == cases
    assert dropped == []


def test_multiple_groups_and_singleton_handled_together():
    a = _case(1, "ВТБ запускает детский банк", "ВТБ", importance=90)
    b = _case(2, "ВТБ запустил детский онлайн-банк", "ВТБ", importance=70)
    c = _case(3, "Уникальный кейс", "Z", importance=50)

    def llm_call(method_name, cases_payload):
        return [[1, 2]]  # только a/b — дубли, c одиночный

    kept, dropped = dedupe_cases([a, b, c], llm_call=llm_call)

    assert kept == [a, c]
    assert dropped == [(b, a)]


def test_group_of_three_keeps_highest_importance():
    """Все 4 реальных заголовка про крипторасчёты Сбера (в этом тесте — 3)
    должны схлопнуться в один кейс — ровно тот баг, что был в дайджесте
    1-8 сентября."""
    low = _case(1, "Сбер запускает криптоплатежи для международных расчётов", "Сбер", importance=40)
    mid = _case(2, "Сбер запускает международные расчёты в криптовалюте", "Сбер", importance=60)
    high = _case(3, "Сбер открыл трансграничные расчеты в криптовалюте для корпоративных клиентов", "Сбер", importance=85)

    def llm_call(method_name, cases_payload):
        return [[1, 2, 3]]

    kept, dropped = dedupe_cases([low, mid, high], llm_call=llm_call)

    assert kept == [high]
    assert {id(d) for d, k in dropped} == {id(low), id(mid)}
    assert all(k is high for _, k in dropped)


def test_llm_call_exception_falls_back_to_no_dedup():
    cases = [
        _case(1, "Кейс A", "A", importance=90),
        _case(2, "Кейс A ещё раз", "A", importance=70),
    ]

    def llm_call(method_name, cases_payload):
        raise RuntimeError("DeepSeek timeout")

    kept, dropped = dedupe_cases(cases, llm_call=llm_call)
    assert kept == cases
    assert dropped == []


def test_llm_returns_group_referencing_unknown_id_ignored():
    cases = [
        _case(1, "Кейс A", "A", importance=90),
        _case(2, "Кейс B", "B", importance=70),
    ]

    def llm_call(method_name, cases_payload):
        return [[1, 999]]  # 999 не существует в пуле

    kept, dropped = dedupe_cases(cases, llm_call=llm_call)
    assert kept == cases
    assert dropped == []


def test_llm_returns_single_element_group_ignored():
    cases = [
        _case(1, "Кейс A", "A", importance=90),
        _case(2, "Кейс B", "B", importance=70),
    ]

    def llm_call(method_name, cases_payload):
        return [[1]]  # группа из одного элемента — не дубль-кластер

    kept, dropped = dedupe_cases(cases, llm_call=llm_call)
    assert kept == cases
    assert dropped == []


def test_case_without_id_never_dropped():
    with_id = _case(1, "Кейс с id", "A", importance=80)
    no_id = {"id": None, "case_title": "Кейс без id", "company": "A", "importance_score": 90}

    def llm_call(method_name, cases_payload):
        # Кейс без id не должен даже попасть в payload.
        assert all(c["id"] is not None for c in cases_payload)
        return []

    kept, dropped = dedupe_cases([with_id, no_id], llm_call=llm_call)
    assert kept == [with_id, no_id]
    assert dropped == []


def test_kept_cases_preserve_original_relative_order():
    a = _case(1, "Кейс A", "A", importance=50)
    b = _case(2, "Кейс B — оригинал", "B", importance=90)
    c = _case(3, "Кейс C", "C", importance=50)
    d = _case(4, "Кейс B — republish", "B", importance=60)

    def llm_call(method_name, cases_payload):
        return [[2, 4]]

    kept, dropped = dedupe_cases([a, b, c, d], llm_call=llm_call)

    assert kept == [a, b, c]
    assert dropped == [(d, b)]


def test_llm_call_receives_truncated_description_and_correct_shape():
    long_description = "x" * 500
    cases = [
        _case(1, "Кейс A", "A", importance=80, description=long_description),
        _case(2, "Кейс B", "B", importance=60, description="короткое"),
    ]

    captured = {}

    def llm_call(method_name, cases_payload):
        captured["payload"] = cases_payload
        return []

    dedupe_cases(cases, llm_call=llm_call)

    payload = captured["payload"]
    assert {"id", "case_title", "company", "description"} == set(payload[0].keys())
    assert len(payload[0]["description"]) <= 150
    assert payload[1]["description"] == "короткое"


def test_alfa_beeline_pair_grouped_by_meaning():
    """Alfa: разные формулировки одного и того же события — LLM видит смысл,
    без порогов схожести строк."""
    kept_case = _case(
        1, "Альфа-Банк и Beeline Cloud создали гибридную ИИ-инфраструктуру",
        "Альфа-Банк", importance=80,
    )
    dropped_case = _case(
        2, "Альфа-Банк развернул ИИ-платформу на мощностях Beeline Cloud",
        "Альфа-Банк", importance=70,
    )

    def llm_call(method_name, cases_payload):
        return [[1, 2]]

    kept, dropped = dedupe_cases([kept_case, dropped_case], llm_call=llm_call)
    assert kept == [kept_case]
    assert dropped == [(dropped_case, kept_case)]


def test_llm_correctly_separates_different_events_same_company():
    """Негатив: одна компания, но разные события — LLM не группирует их
    (в отличие от порогового fuzzy-сравнения, которое видело бы схожесть слов)."""
    a = _case(1, "Сбер запустил крипторасчеты для бизнеса", "Сбер", importance=80)
    b = _case(2, "Сбер представил новый мобильный офис для малого бизнеса", "Сбер", importance=70)

    def llm_call(method_name, cases_payload):
        return []  # LLM решила: разные события

    kept, dropped = dedupe_cases([a, b], llm_call=llm_call)
    assert kept == [a, b]
    assert dropped == []
