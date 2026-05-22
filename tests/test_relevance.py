
from processor.relevance import compute_relevance


class TestComputeRelevance:
    def test_returns_tuple(self):
        score, label = compute_relevance(["Финансы"], ["ставка"], False, "текст " * 20)
        assert isinstance(score, int)
        assert isinstance(label, str)

    def test_score_in_range(self):
        score, _ = compute_relevance(["Финансы"], [], False, "текст " * 20)
        assert 0 <= score <= 100

    def test_ad_reduces_score(self):
        score_no_ad, _ = compute_relevance(["Финансы"], ["ставка"], False, "текст " * 20)
        score_ad, _ = compute_relevance(["Финансы"], ["ставка"], True, "текст " * 20)
        assert score_ad < score_no_ad

    def test_short_text_reduces_score(self):
        score_short, _ = compute_relevance(["Финансы"], [], False, "кратко")
        score_long, _ = compute_relevance(["Финансы"], [], False, "длинный текст " * 15)
        assert score_short < score_long

    def test_high_label_for_high_score(self):
        # Биометрия(25) + ИИ(25) + combo(12) + >=2 non-generic(10) → 72+ → high
        score, label = compute_relevance(
            ["Биометрия", "ИИ"], ["биометрия", "llm", "нейросеть", "распознавание", "токены"],
            False, "очень длинный текст " * 10,
        )
        assert label == "high"
        assert score >= 60

    def test_irrelevant_label_for_low_score(self):
        _, label = compute_relevance([], [], True, "")
        assert label == "irrelevant"

    def test_no_topics_no_tags_not_ad_medium_text(self):
        score, label = compute_relevance([], [], False, "текст " * 20)
        assert score >= 0
        assert label in ("irrelevant", "low", "medium", "high")
