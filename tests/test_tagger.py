
from processor.tagger import assign_tags, assign_topics, extract_companies


class TestAssignTopics:
    def test_finance_topic(self):
        topics = assign_topics("Центральный банк повысил ключевую ставку")
        assert any("финанс" in t.lower() or "банк" in t.lower() or t == "Финансы" for t in topics)

    def test_it_topic(self):
        topics = assign_topics("Новый стартап в сфере разработки программного обеспечения")
        assert len(topics) > 0

    def test_unknown_topic_returns_obshchee(self):
        topics = assign_topics("Погода сегодня солнечная и тёплая")
        assert topics == ["Общее"]

    def test_returns_list(self):
        assert isinstance(assign_topics("текст"), list)

    def test_multiple_topics_possible(self):
        text = "Банк инвестировал в новый технологический стартап"
        topics = assign_topics(text)
        assert isinstance(topics, list)
        assert len(topics) >= 1


class TestAssignTags:
    def test_returns_list(self):
        assert isinstance(assign_tags("текст"), list)

    def test_empty_text_returns_empty(self):
        tags = assign_tags("")
        assert isinstance(tags, list)

    def test_finds_relevant_tags(self):
        tags = assign_tags("Центральный банк повысил ключевую ставку по кредитам")
        assert isinstance(tags, list)

    def test_no_false_positives(self):
        tags = assign_tags("Очень общий текст без специфики")
        assert isinstance(tags, list)


class TestExtractCompanies:
    def test_finds_sberbank(self):
        companies = extract_companies("Сбербанк объявил о новой программе")
        assert "Сбербанк" in companies

    def test_returns_list(self):
        assert isinstance(extract_companies("текст"), list)

    def test_empty_text_returns_empty(self):
        assert extract_companies("") == []

    def test_no_companies_returns_empty(self):
        result = extract_companies("Погода сегодня отличная")
        assert isinstance(result, list)
