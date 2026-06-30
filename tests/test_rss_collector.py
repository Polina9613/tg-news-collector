"""Tests for RSS collector: _parse_date, _entry_hash, load_rss_sources, collect_rss_source."""
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from collector.rss import RssCollectResult, _entry_hash, _parse_date, collect_rss_source
from collector.sources_loader import load_rss_sources


class TestParseDate:
    def test_parse_published_parsed(self):
        entry = MagicMock(spec=[])
        entry.published_parsed = (2024, 6, 15, 10, 30, 0, 0, 0, 0)
        entry.updated_parsed = None
        assert _parse_date(entry) == datetime(2024, 6, 15, 10, 30, 0)

    def test_fallback_to_updated_parsed(self):
        entry = MagicMock(spec=[])
        entry.published_parsed = None
        entry.updated_parsed = (2024, 6, 10, 8, 0, 0, 0, 0, 0)
        assert _parse_date(entry) == datetime(2024, 6, 10, 8, 0, 0)

    def test_fallback_to_now_when_no_dates(self):
        entry = MagicMock(spec=[])
        entry.published_parsed = None
        entry.updated_parsed = None
        before = datetime.utcnow()
        result = _parse_date(entry)
        after = datetime.utcnow()
        assert isinstance(result, datetime)
        assert before <= result <= after


class TestEntryHash:
    def test_returns_positive_int(self):
        h = _entry_hash("@source1", "entry123")
        assert isinstance(h, int)
        assert h > 0

    def test_same_inputs_give_same_hash(self):
        assert _entry_hash("@cbr_rss", "abc-123") == _entry_hash("@cbr_rss", "abc-123")

    def test_different_sources_different_hash(self):
        h1 = _entry_hash("@source1", "entry123")
        h2 = _entry_hash("@source2", "entry123")
        assert h1 != h2

    def test_different_entries_different_hash(self):
        h1 = _entry_hash("@source1", "entry123")
        h2 = _entry_hash("@source1", "entry456")
        assert h1 != h2


class TestLoadRssSources:
    def test_loads_active_sources(self, tmp_path):
        yaml_text = """
rss_sources:
  - username: '@cbr_rss'
    title: ЦБ РФ
    feed_url: https://cbr.ru/rss.xml
    active: true
    topics: [банки]
  - username: '@inactive'
    title: Неактивный
    feed_url: https://example.com/rss
    active: false
"""
        f = tmp_path / "sources.yaml"
        f.write_text(yaml_text, encoding="utf-8")
        sources = load_rss_sources(str(f))
        assert len(sources) == 1
        assert sources[0]["username"] == "@cbr_rss"

    def test_missing_section_returns_empty(self, tmp_path):
        yaml_text = "channels:\n  - username: '@test'\n    title: Test\n"
        f = tmp_path / "sources.yaml"
        f.write_text(yaml_text, encoding="utf-8")
        assert load_rss_sources(str(f)) == []

    def test_missing_feed_url_skipped(self, tmp_path):
        yaml_text = """
rss_sources:
  - username: '@no_url'
    title: No URL
    active: true
"""
        f = tmp_path / "sources.yaml"
        f.write_text(yaml_text, encoding="utf-8")
        assert load_rss_sources(str(f)) == []


# ── DB-зависимые тесты ────────────────────────────────────────────────────────

def _make_rss_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from db.base import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    _Session = sessionmaker(engine, autocommit=False, autoflush=False)

    @contextmanager
    def _get_session():
        s = _Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    return engine, _get_session


def _make_entry(entry_id, title, text, pub_date_tuple=None):
    e = MagicMock()
    e.id = entry_id
    e.link = f"https://example.com/{entry_id}"
    e.title = title
    e.summary = text
    e.description = text
    e.published_parsed = pub_date_tuple
    e.updated_parsed = None
    return e


class TestCollectRssSource:
    @pytest.fixture(autouse=True)
    def _rss_db(self):
        engine, gs = _make_rss_db()
        with patch("collector.rss.get_session", gs):
            self._gs = gs
            self._engine = engine
            yield
        engine.dispose()

    def test_skips_old_entries(self):
        mock_feed = MagicMock()
        mock_feed.entries = [
            _make_entry("old-1", "Old", "text", (2020, 1, 1, 0, 0, 0, 0, 0, 0)),
        ]
        with patch("collector.rss.feedparser.parse", return_value=mock_feed), \
             patch("collector.rss.time.sleep"):
            result = collect_rss_source(1, "@test_rss", "https://ex.com/rss", days=7)
        assert result.saved == 0
        assert result.total_fetched == 1

    def test_saves_new_entry(self):
        from db.models import Source
        with self._gs() as s:
            src = Source(username="@rss_new", title="RSS New", topics="[]", is_active=True)
            s.add(src)
            s.flush()
            src_id = src.id

        mock_feed = MagicMock()
        mock_feed.entries = [
            _make_entry("entry-1", "Title", "Fintech text", (2026, 6, 29, 12, 0, 0, 0, 0, 0)),
        ]
        with patch("collector.rss.feedparser.parse", return_value=mock_feed), \
             patch("collector.rss.time.sleep"):
            result = collect_rss_source(src_id, "@rss_new", "https://ex.com/rss", days=7)
        assert result.saved == 1
        assert result.errors == 0

    def test_deduplicates_entry(self):
        from db.models import RawPost, Source
        with self._gs() as s:
            src = Source(username="@rss_dup", title="RSS Dup", topics="[]", is_active=True)
            s.add(src)
            s.flush()
            src_id = src.id
            mid = _entry_hash("@rss_dup", "dup-entry-1")
            post = RawPost(
                source_id=src_id, message_id=mid,
                channel_username="@rss_dup",
                post_url="https://ex.com/dup-entry-1",
                raw_text="Already saved", text_hash="abc123",
                published_at=datetime.utcnow(),
                has_media=False, is_forwarded=False,
            )
            s.add(post)

        mock_feed = MagicMock()
        mock_feed.entries = [
            _make_entry("dup-entry-1", "Dup", "text", (2026, 6, 29, 12, 0, 0, 0, 0, 0)),
        ]
        with patch("collector.rss.feedparser.parse", return_value=mock_feed), \
             patch("collector.rss.time.sleep"):
            result = collect_rss_source(src_id, "@rss_dup", "https://ex.com/rss", days=7)
        assert result.skipped_duplicate == 1
        assert result.saved == 0

    def test_accepts_source_title_param(self):
        mock_feed = MagicMock()
        mock_feed.entries = []
        with patch("collector.rss.feedparser.parse", return_value=mock_feed):
            result = collect_rss_source(
                1, "@test", "https://ex.com/rss",
                days=7, source_title="Test Feed",
            )
        assert isinstance(result, RssCollectResult)
