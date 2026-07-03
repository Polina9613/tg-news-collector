"""Tests for processor/prefilter.py"""
from processor.prefilter import should_skip_llm


def test_empty_text_is_skipped():
    skip, reason = should_skip_llm("")
    assert skip is True
    assert "too_short" in reason


def test_too_short_text_is_skipped():
    skip, reason = should_skip_llm("Короткий")
    assert skip is True
    assert "too_short" in reason


def test_contest_pattern_is_skipped():
    skip, reason = should_skip_llm(
        "Объявляем конкурс среди наших подписчиков! Призы и подарки ждут победителей."
    )
    assert skip is True
    assert "конкурс" in reason.lower()


def test_vacancy_pattern_is_skipped():
    skip, reason = should_skip_llm(
        "Мы ищем опытного разработчика Python для нашей команды. Отличные условия труда."
    )
    assert skip is True


def test_relevant_fintech_text_is_not_skipped():
    skip, reason = should_skip_llm(
        "Сбербанк запустил новый сервис биометрической идентификации "
        "в 15 000 банкоматов по всей России. Технология Face Pay теперь "
        "доступна клиентам без использования карты или телефона."
    )
    assert skip is False
    assert reason == ""


def test_normal_length_text_is_not_skipped():
    text = "Ц" * 100
    skip, reason = should_skip_llm(text)
    assert skip is False
