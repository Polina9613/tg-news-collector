"""Tests for split digest LLM calls: generate_main_summary / generate_topic_analysis."""
from unittest.mock import MagicMock


def test_generate_main_summary_returns_clusters():
    from digest.llm_digest import generate_main_summary

    provider = MagicMock()
    provider._call.return_value = (
        '{"main_summary_clusters": ['
        '{"intro": "Крипторасчёты набирают обороты", '
        '"bullets": ["Сбер запустил крипторасчеты, что указывает на рост спроса"]}'
        ']}'
    )
    result = generate_main_summary(provider, [{"case_title": "X", "company": "Y"}])
    assert result == [
        {
            "intro": "Крипторасчёты набирают обороты",
            "bullets": ["Сбер запустил крипторасчеты, что указывает на рост спроса"],
        }
    ]


def test_generate_main_summary_empty_on_error():
    from digest.llm_digest import generate_main_summary

    provider = MagicMock()
    provider._call.side_effect = Exception("timeout")
    result = generate_main_summary(provider, [])
    assert result == []


def test_generate_main_summary_empty_on_bad_json():
    from digest.llm_digest import generate_main_summary

    provider = MagicMock()
    provider._call.return_value = "not json at all"
    result = generate_main_summary(provider, [{"case_title": "X", "company": "Y"}])
    assert result == []


def test_generate_main_summary_ignores_non_dict_cluster_entries():
    """Защита от кривого ответа LLM: не-dict элементы в массиве отбрасываются."""
    from digest.llm_digest import generate_main_summary

    provider = MagicMock()
    provider._call.return_value = (
        '{"main_summary_clusters": [{"intro": "OK", "bullets": ["b1"]}, "не словарь", 42]}'
    )
    result = generate_main_summary(provider, [{"case_title": "X", "company": "Y"}])
    assert result == [{"intro": "OK", "bullets": ["b1"]}]


def test_generate_main_summary_defaults_missing_fields():
    """intro/bullets отсутствуют в кластере — не падаем, подставляем дефолты."""
    from digest.llm_digest import generate_main_summary

    provider = MagicMock()
    provider._call.return_value = '{"main_summary_clusters": [{}]}'
    result = generate_main_summary(provider, [{"case_title": "X", "company": "Y"}])
    assert result == [{"intro": "", "bullets": []}]


def test_generate_topic_analysis_returns_both_fields():
    from digest.llm_digest import generate_topic_analysis

    provider = MagicMock()
    provider._call.return_value = (
        '{"topic_conclusions": {"Тема1": "вывод"}, "overall_conclusions": ["вектор1"]}'
    )
    result = generate_topic_analysis(
        provider, {"Тема1": [{"company": "X", "case_title": "Y"}]}
    )
    assert result["topic_conclusions"] == {"Тема1": "вывод"}
    assert result["overall_conclusions"] == ["вектор1"]


def test_generate_topic_analysis_empty_on_error():
    from digest.llm_digest import generate_topic_analysis

    provider = MagicMock()
    provider._call.side_effect = Exception("500 error")
    result = generate_topic_analysis(provider, {})
    assert result["topic_conclusions"] == {}
    assert result["overall_conclusions"] == []


def test_generate_topic_analysis_passes_all_topics_to_prompt():
    """Все переданные темы должны попасть в промпт."""
    from digest.llm_digest import generate_topic_analysis

    provider = MagicMock()
    provider._call.return_value = '{"topic_conclusions": {}, "overall_conclusions": []}'

    topics = {
        "Тема А": [{"company": "Сбер", "case_title": "Запуск"}],
        "Тема Б": [{"company": "ВТБ", "case_title": "Обновление"}],
    }
    generate_topic_analysis(provider, topics)

    call_user_prompt = provider._call.call_args[0][1]
    assert "Тема А" in call_user_prompt
    assert "Тема Б" in call_user_prompt


def test_topic_analysis_prompt_requests_five_to_six_cross_topic_vectors():
    """Промт должен просить 5-6 сквозных векторов между темами, не по одному
    выводу на тему."""
    from digest.llm_digest import _TOPIC_ANALYSIS_SYSTEM

    assert "5-6" in _TOPIC_ANALYSIS_SYSTEM
    assert "МЕЖДУ темами" in _TOPIC_ANALYSIS_SYSTEM
