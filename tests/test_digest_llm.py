"""Tests for split digest LLM calls: generate_main_summary / generate_topic_analysis."""
from unittest.mock import MagicMock


def test_generate_main_summary_returns_string():
    from digest.llm_digest import generate_main_summary

    provider = MagicMock()
    provider._call.return_value = '{"main_summary": "Текст главного за неделю"}'
    result = generate_main_summary(provider, [{"case_title": "X", "company": "Y"}])
    assert result == "Текст главного за неделю"


def test_generate_main_summary_empty_on_error():
    from digest.llm_digest import generate_main_summary

    provider = MagicMock()
    provider._call.side_effect = Exception("timeout")
    result = generate_main_summary(provider, [])
    assert result == ""


def test_generate_main_summary_empty_on_bad_json():
    from digest.llm_digest import generate_main_summary

    provider = MagicMock()
    provider._call.return_value = "not json at all"
    result = generate_main_summary(provider, [{"case_title": "X", "company": "Y"}])
    assert result == ""


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
