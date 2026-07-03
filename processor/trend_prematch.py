"""
Быстрое сопоставление кейса с трендом по ключевым словам — без LLM.
Используется как подсказка ПЕРЕД assign_trend, не как замена —
если pre-match даёт однозначный высокоуверенный результат, можно
использовать его напрямую и не тратить LLM-вызов на assign_trend.
"""
import re

TREND_KEYWORDS = {
    1: ["face pay", "биометри", "отпечат", "распознавание лица", "ладон"],
    2: ["nfc", "tap-to-pay", "qr-код", "оплата смартфон", "apple pay", "google pay"],
    5: ["цифровой рубль", "cbdc", "цифровая валюта банка"],
    6: ["биткоин", "криптовалют", "эфириум", "майнинг"],
    8: ["ии-агент", "автономный ассистент", "llm-ассистент"],
}

_COMPILED = {
    tid: re.compile("|".join(re.escape(k) for k in kws), re.IGNORECASE)
    for tid, kws in TREND_KEYWORDS.items()
}


def prematch_trend(case_title: str, description: str) -> int | None:
    """
    Возвращает trend_id если есть однозначное совпадение по ключевым словам,
    иначе None. Консервативен — при любой неоднозначности возвращает None.
    """
    text = f"{case_title} {description}".lower()
    matches = [tid for tid, pattern in _COMPILED.items() if pattern.search(text)]

    if len(matches) == 1:
        return matches[0]
    return None
