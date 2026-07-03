import re

MIN_TEXT_LENGTH = 40
MAX_EMOJI_RATIO = 0.3

STOP_PATTERNS = [
    re.compile(r"(конкурс|giveaway|розыгрыш)", re.IGNORECASE),
    re.compile(r"(вакансия|стажировка|мы ищем|требуется|hiring|wanted)", re.IGNORECASE),
    re.compile(r"(реклама|партнёрский материал|рекл\.|adv\.|sponsored)", re.IGNORECASE),
    re.compile(r"(подписывайтесь|подпишитесь|следите за нами|наш канал)", re.IGNORECASE),
    re.compile(r"(скидка \d+%|промокод|promo code|чёрная пятница)", re.IGNORECASE),
]


def _emoji_ratio(text: str) -> float:
    if not text:
        return 0.0
    count = sum(
        1
        for ch in text
        if "\U0001F300" <= ch <= "\U0001FAFF"
        or "\U00002600" <= ch <= "\U000027BF"
        or "\U0001F1E0" <= ch <= "\U0001F1FF"
    )
    return count / len(text)


def should_skip_llm(text: str) -> tuple[bool, str]:
    """
    Быстрый rule-based фильтр перед отправкой в LLM.
    Возвращает (True, причина) если пост нужно пропустить.
    """
    if not text or len(text) < MIN_TEXT_LENGTH:
        return True, f"too_short ({len(text)} chars)"

    if _emoji_ratio(text) > MAX_EMOJI_RATIO:
        return True, f"emoji_spam ({_emoji_ratio(text):.0%} emojis)"

    for pattern in STOP_PATTERNS:
        m = pattern.search(text)
        if m:
            return True, f"stop_pattern: {m.group(0)!r}"

    return False, ""
