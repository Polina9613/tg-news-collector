AD_MARKERS = [
    "#реклама",
    "реклама",
    "рекламодатель",
    "erid",
    "на правах рекламы",
    "партнёрский материал",
    "партнерский материал",
    "18+",
    "ооо ",    # с пробелом, чтобы не ловить слова типа "зоологоо"
    " инн ",   # с пробелами
]


def detect_ad(text: str) -> bool:
    text_lower = text.lower()
    return any(marker in text_lower for marker in AD_MARKERS)
