"""
Integration tests: collect → process → enrich → export pipeline.
Each test uses an isolated in-memory SQLite DB via patched get_session.
"""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import NewsCard, RawPost, Source, Trend, TrendCase


# ── Shared in-memory DB fixture ───────────────────────────────────────────────

@pytest.fixture
def mem_db():
    """
    In-memory SQLite with StaticPool + patched get_session in all relevant modules.
    Yields (engine, get_session_fn).
    """
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

    targets = [
        "db.base.get_session",
        "llm.enricher.get_session",
        "exporter.excel.get_session",
        "processor.pipeline.get_session",
        "processor.early_dedup.get_session",
    ]
    with ExitStack() as stack:
        for t in targets:
            stack.enter_context(patch(t, _get_session))
        yield engine, _get_session

    engine.dispose()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_source_and_post(gs, suffix="", raw_text="Fintech news text here."):
    """Creates Source + RawPost; returns (source, post)."""
    with gs() as s:
        src = Source(
            username=f"@integ{suffix}",
            title=f"Integ Channel{suffix}",
            topics='["финтех"]',
            is_active=True,
        )
        s.add(src)
        s.flush()
        post = RawPost(
            source_id=src.id,
            message_id=abs(hash(suffix)) % 1_000_000,
            channel_username=f"@integ{suffix}",
            post_url=f"https://t.me/integ{suffix}/1",
            raw_text=raw_text,
            text_hash=f"hash{suffix}",
            published_at=datetime.utcnow(),
            has_media=False,
            is_forwarded=False,
        )
        s.add(post)
        s.flush()
        return src.id, post.id


def _create_card(gs, raw_post_id, score=50, enriched=False, title="Test Card"):
    """Creates a NewsCard; returns card.id."""
    with gs() as s:
        card = NewsCard(
            raw_post_id=raw_post_id,
            title=title,
            source_title="Test Channel",
            post_url="https://t.me/test/1",
            published_at=datetime.utcnow(),
            clean_text="Сбер запустил биометрию в 15 000 банкоматов.",
            relevance_score=score,
            relevance_label="high",
            llm_enriched=enriched,
        )
        s.add(card)
        s.flush()
        return card.id


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestProcessRawPosts:
    def test_creates_news_card_from_raw_post(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_proc1")

        from processor.pipeline import process_raw_posts
        result = process_raw_posts()

        assert result.total >= 1
        assert result.created >= 1

        with gs() as s:
            card = s.query(NewsCard).filter(NewsCard.raw_post_id == post_id).first()
        assert card is not None

    def test_skips_already_processed_posts(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_proc2")
        _create_card(gs, post_id)

        from processor.pipeline import process_raw_posts
        result = process_raw_posts()

        # Posts with an existing NewsCard are filtered out at the query level,
        # so they don't even appear in total — they are silently skipped.
        assert result.created == 0
        assert result.total == 0

    def test_process_result_has_correct_shape(self, mem_db):
        engine, gs = mem_db
        from processor.pipeline import ProcessResult, process_raw_posts

        result = process_raw_posts()
        assert hasattr(result, "total")
        assert hasattr(result, "created")
        assert hasattr(result, "skipped_duplicate")
        assert hasattr(result, "skipped_empty")
        assert hasattr(result, "errors")


class TestEnrichNewsCards:
    def _mock_provider(self):
        p = MagicMock()
        p.check_relevance_and_classify.return_value = {
            "relevant": True,
            "relevance_reason": "финтех-кейс",
            "type": "case",
            "case_count": 1,
            "classify_reason": "конкретный продукт",
        }
        p.extract_cases.return_value = [{
            "case_title": "Сбер Face Pay 15k банкоматов",
            "company": "Сбер",
            "description": "Запуск биометрии.",
            "how_it_works": "Face ID.",
            "value": "Ускорение оплаты.",
            "market": "Россия",
            "industry": "Финтех / банки",
            "source_url": None,
        }]
        p.assign_trend.return_value = {"decision": "none", "trend_id": None,
                                       "new_trend_name": None, "new_trend_description": None}
        return p

    def test_creates_trend_case(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_enrich1")
        card_id = _create_card(gs, post_id, score=60, enriched=False)

        from llm.enricher import enrich_news_cards
        with patch("llm.enricher.time.sleep"):
            result = enrich_news_cards(self._mock_provider(), min_score=25, limit=5)

        assert result.cases_created >= 1
        with gs() as s:
            cases = s.query(TrendCase).filter(TrendCase.news_card_id == card_id).all()
        assert len(cases) >= 1

    def test_marks_card_enriched(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_enrich2")
        card_id = _create_card(gs, post_id, score=60, enriched=False)

        from llm.enricher import enrich_news_cards
        with patch("llm.enricher.time.sleep"):
            enrich_news_cards(self._mock_provider(), min_score=25, limit=5)

        with gs() as s:
            card = s.get(NewsCard, card_id)
            assert card.llm_enriched is True

    def test_skips_card_below_min_score(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_enrich3")
        _create_card(gs, post_id, score=10, enriched=False)

        from llm.enricher import enrich_news_cards
        with patch("llm.enricher.time.sleep"):
            result = enrich_news_cards(self._mock_provider(), min_score=25, limit=5)

        assert result.total == 0

    def test_skips_already_enriched_card(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_enrich4")
        _create_card(gs, post_id, score=80, enriched=True)

        from llm.enricher import enrich_news_cards
        with patch("llm.enricher.time.sleep"):
            result = enrich_news_cards(self._mock_provider(), min_score=25, limit=5)

        assert result.total == 0

    def test_irrelevant_card_not_case(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_enrich5")
        _create_card(gs, post_id, score=60, enriched=False)

        provider = self._mock_provider()
        provider.check_relevance_and_classify.return_value = {
            "relevant": False,
            "relevance_reason": "off-topic",
            "type": "news",
            "case_count": 0,
            "classify_reason": "",
        }

        from llm.enricher import enrich_news_cards
        with patch("llm.enricher.time.sleep"):
            result = enrich_news_cards(provider, min_score=25, limit=5)

        assert result.irrelevant == 1
        assert result.cases_created == 0

    def test_fallback_provider_used_on_primary_failure(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_fallback")
        _create_card(gs, post_id, score=60, enriched=False)

        primary = MagicMock()
        primary.check_relevance_and_classify.side_effect = Exception("Primary failed")

        fallback = self._mock_provider()

        from llm.enricher import enrich_news_cards
        with patch("llm.enricher.time.sleep"):
            result = enrich_news_cards(primary, min_score=25, limit=5, fallback_provider=fallback)

        assert result.relevant >= 1
        fallback.check_relevance_and_classify.assert_called_once()


class TestDuplicateDetection:
    def test_detects_duplicate_same_company_similar_title(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_dup1")
        card_id = _create_card(gs, post_id, score=60)

        with gs() as s:
            existing = TrendCase(
                news_card_id=card_id,
                case_title="Сбер запускает биометрию в банкоматах",
                company="Сбер",
                description="описание",
                is_duplicate=False,
                created_at=datetime.utcnow(),
            )
            s.add(existing)
            s.flush()
            existing_id = existing.id

        from llm.enricher import _check_duplicate
        dup_id = _check_duplicate({
            "case_title": "Сбер запустил биометрию банкоматах",
            "company": "Сбер",
        })
        assert dup_id == existing_id

    def test_no_duplicate_different_company(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_dup2")
        card_id = _create_card(gs, post_id, score=60)

        with gs() as s:
            tc = TrendCase(
                news_card_id=card_id,
                case_title="Сбер запускает биометрию в банкоматах",
                company="Сбер",
                description="описание",
                is_duplicate=False,
                created_at=datetime.utcnow(),
            )
            s.add(tc)

        from llm.enricher import _check_duplicate
        dup_id = _check_duplicate({
            "case_title": "Сбер запускает биометрию в банкоматах",
            "company": "ВТБ",
        })
        assert dup_id is None

    def test_no_duplicate_different_title(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_dup3")
        card_id = _create_card(gs, post_id, score=60)

        with gs() as s:
            tc = TrendCase(
                news_card_id=card_id,
                case_title="Сбер Face Pay в торговых центрах",
                company="Сбер",
                description="описание",
                is_duplicate=False,
                created_at=datetime.utcnow(),
            )
            s.add(tc)

        from llm.enricher import _check_duplicate
        dup_id = _check_duplicate({
            "case_title": "Сбер запускает биометрию банкоматах",
            "company": "Сбер",
        })
        assert dup_id is None

    def test_no_duplicate_when_db_empty(self, mem_db):
        from llm.enricher import _check_duplicate
        assert _check_duplicate({"case_title": "Тест", "company": "Сбер"}) is None

    def test_no_duplicate_for_old_case(self, mem_db):
        engine, gs = mem_db
        _src_id, post_id = _create_source_and_post(gs, suffix="_dup4")
        card_id = _create_card(gs, post_id)

        old_date = datetime.utcnow() - timedelta(days=10)
        with gs() as s:
            tc = TrendCase(
                news_card_id=card_id,
                case_title="Сбер запускает биометрию в банкоматах",
                company="Сбер",
                description="desc",
                is_duplicate=False,
                created_at=old_date,
            )
            s.add(tc)

        from llm.enricher import _check_duplicate
        dup_id = _check_duplicate({
            "case_title": "Сбер запускает биометрию в банкоматах",
            "company": "Сбер",
        }, since_days=5)
        assert dup_id is None


# ── _prepare_text ─────────────────────────────────────────────────────────────

def test_prepare_text_truncates_long():
    from llm.enricher import _prepare_text

    class C:
        clean_text = "А" * 3000

    result = _prepare_text(C())
    assert len(result) <= 1600
    assert "[текст обрезан]" in result


def test_prepare_text_keeps_short():
    from llm.enricher import _prepare_text

    class C:
        clean_text = "Короткий текст"

    result = _prepare_text(C())
    assert result == "Короткий текст"


# ── retry_after ───────────────────────────────────────────────────────────────

# ── _compress_text ────────────────────────────────────────────────────────────

def test_compress_removes_emoji_decoration():
    from llm.enricher import _compress_text
    text = "Важная новость 🔥🔥🔥🔥🔥 про финтех"
    result = _compress_text(text)
    assert "🔥🔥🔥🔥🔥" not in result
    assert "Важная новость" in result
    assert "финтех" in result


def test_compress_removes_hashtag_block():
    from llm.enricher import _compress_text
    text = "Сбербанк запустил новый продукт для клиентов\n#финтех #банки #новости #сбер"
    result = _compress_text(text)
    assert "#финтех" not in result
    assert "Сбербанк запустил новый продукт" in result


def test_compress_keeps_meaningful_hashtags_inline():
    from llm.enricher import _compress_text
    text = "Обсуждаем главные новости #финтех индустрии сегодня в деталях"
    result = _compress_text(text)
    assert "#финтех" in result


def test_compress_collapses_whitespace():
    from llm.enricher import _compress_text
    text = "Текст    с     лишними      пробелами"
    result = _compress_text(text)
    assert "    " not in result
    assert "Текст" in result
    assert "пробелами" in result


def test_card_sent_to_back_of_queue_on_timeout(mem_db):
    """При таймауте карточка получает llm_retry_after, а не помечается enriched."""
    engine, gs = mem_db
    _src_id, post_id = _create_source_and_post(gs, suffix="_timeout")
    card_id = _create_card(gs, post_id, score=80, enriched=False)

    mock_provider = MagicMock()
    mock_provider.check_relevance_and_classify.side_effect = TimeoutError("timed out")

    from llm.enricher import enrich_news_cards
    with patch("llm.enricher.time.sleep"):
        result = enrich_news_cards(mock_provider, min_score=0, limit=1)

    assert result.errors == 1
    with gs() as s:
        c = s.get(NewsCard, card_id)
        assert c.llm_enriched is False
        assert c.llm_retry_after is not None
