from processor.tagger import TOPICS_WEIGHTS

TOPIC_COMBO_BONUSES: list[tuple[frozenset, int]] = [
    (frozenset(["Банки", "ИИ"]), 15),
    (frozenset(["Банки", "Биометрия"]), 15),
    (frozenset(["Банки", "Платежи"]), 10),
    (frozenset(["Банки", "Импортозамещение"]), 10),
    (frozenset(["Банки", "Кибербезопасность"]), 10),
    (frozenset(["Банки", "КСО / Самообслуживание"]), 12),
    (frozenset(["Импортозамещение", "ИТ-инфраструктура"]), 10),
    (frozenset(["Импортозамещение", "Кибербезопасность"]), 10),
    (frozenset(["МСБ", "Финтех"]), 10),
    (frozenset(["МСБ", "Банки"]), 8),
    (frozenset(["ИИ", "Финтех"]), 12),
    (frozenset(["ИИ", "КСО / Самообслуживание"]), 12),
    (frozenset(["Платежи", "Биометрия"]), 12),
    (frozenset(["Платежи", "Регуляторика"]), 8),
]


def compute_relevance(
    topics: list[str],
    tags: list[str],
    is_ad: bool,
    text: str,
) -> tuple[int, str]:
    score = 0
    topics_set = set(topics)

    # 1. Веса тем
    for topic in topics:
        score += TOPICS_WEIGHTS.get(topic, 10)

    # 2. Теги: +4 за каждый, макс 20
    score += min(len(tags) * 4, 20)

    # 3. Бонус если найдены две и более небазовых тем
    if len([t for t in topics if t != "Общее"]) >= 2:
        score += 10

    # 4. Комбо-бонусы за сочетания тем
    for combo, bonus in TOPIC_COMBO_BONUSES:
        if combo.issubset(topics_set):
            score += bonus

    # 5. Штрафы
    if is_ad:
        score -= 20
    if len(text) < 100:
        score -= 30

    # 6. Clamp 0..100
    score = max(0, min(100, score))

    if score >= 60:
        label = "high"
    elif score >= 35:
        label = "medium"
    elif score >= 10:
        label = "low"
    else:
        label = "irrelevant"

    return score, label
