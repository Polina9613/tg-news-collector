import json

from processor.card_builder import build_news_card, pick_source_url


class TestBuildNewsCard:
    def test_returns_news_card(self, db_session, sample_raw_post):
        card = build_news_card(sample_raw_post, db_session)
        assert card is not None

    def test_empty_post_returns_none(self, db_session, sample_raw_post_empty):
        card = build_news_card(sample_raw_post_empty, db_session)
        assert card is None

    def test_card_has_title(self, db_session, sample_raw_post):
        card = build_news_card(sample_raw_post, db_session)
        assert card is not None
        assert card.title is not None
        assert len(card.title) > 0

    def test_card_has_clean_text(self, db_session, sample_raw_post):
        card = build_news_card(sample_raw_post, db_session)
        assert card is not None
        assert card.clean_text is not None

    def test_card_topics_is_json_list(self, db_session, sample_raw_post):
        card = build_news_card(sample_raw_post, db_session)
        assert card is not None
        topics = json.loads(card.topics)
        assert isinstance(topics, list)

    def test_card_tags_is_json_list(self, db_session, sample_raw_post):
        card = build_news_card(sample_raw_post, db_session)
        assert card is not None
        tags = json.loads(card.tags)
        assert isinstance(tags, list)

    def test_card_relevance_score_in_range(self, db_session, sample_raw_post):
        card = build_news_card(sample_raw_post, db_session)
        assert card is not None
        assert 0 <= card.relevance_score <= 100

    def test_card_review_status_set(self, db_session, sample_raw_post):
        card = build_news_card(sample_raw_post, db_session)
        assert card is not None
        assert card.review_status in ("auto", "needs_review")


class TestPickSourceUrl:
    def test_prefers_external_over_tme(self):
        urls = '["https://t.me/channel/123", "https://rbc.ru/news/article"]'
        assert pick_source_url(urls) == "https://rbc.ru/news/article"

    def test_fallback_to_post_url_when_only_tme(self):
        urls = '["https://t.me/channel/123"]'
        post_url = "https://t.me/mychannel/456"
        assert pick_source_url(urls, post_url) == post_url

    def test_prefers_trusted_domain(self):
        urls = '["https://example.com/article", "https://rbc.ru/news/item"]'
        assert pick_source_url(urls) == "https://rbc.ru/news/item"

    def test_none_returns_none(self):
        assert pick_source_url(None) is None

    def test_none_with_post_url_returns_post_url(self):
        assert pick_source_url(None, "https://t.me/ch/1") == "https://t.me/ch/1"

    def test_empty_list_returns_none(self):
        assert pick_source_url("[]") is None
