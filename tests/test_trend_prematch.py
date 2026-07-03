"""Tests for processor/trend_prematch.py"""
from processor.trend_prematch import prematch_trend


def test_prematch_face_pay():
    result = prematch_trend("Сбер запустил Face Pay в банкоматах", "Оплата по биометрии лица")
    assert result == 1


def test_prematch_no_match_returns_none():
    result = prematch_trend("Компания открыла новый офис", "Расширение штата")
    assert result is None


def test_prematch_ambiguous_returns_none():
    """Если совпадает несколько трендов — не угадываем, отдаём LLM."""
    result = prematch_trend(
        "Биометрическая оплата через смартфон с NFC",
        "Face pay и qr-код одновременно"
    )
    assert result is None
