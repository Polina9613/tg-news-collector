"""Тесты поиска по подстроке."""
import itertools
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import db.base as _db_base
from db.models import Base, NewsCard, RawPost, Source, TrendCase
from bot.handlers.analyst import _search_cases

_counter = itertools.count(1)


@pytest.fixture
def search_db(monkeypatch):
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(_db_base, "engine", test_engine)
    monkeypatch.setattr(_db_base, "SessionLocal", TestSession)
    yield
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


def _add_case(session, **fields):
    n = next(_counter)
    src = Source(username=f"chan{n}", title="Test Chan", topics='[]', is_active=True)
    session.add(src)
    session.flush()

    rp = RawPost(
        source_id=src.id,
        message_id=n,
        channel_username=f"chan{n}",
        post_url=f"https://t.me/chan{n}/{n}",
        raw_text="test",
        published_at=datetime(2024, 1, 1),
        has_media=False,
        is_forwarded=False,
    )
    session.add(rp)
    session.flush()

    nc = NewsCard(
        raw_post_id=rp.id,
        title=fields.get("title", "Test"),
        clean_text=fields.get("clean_text", "test"),
        source_title="Test",
        relevance_score=fields.get("score", 50),
        relevance_label=fields.get("label", "high"),
        topics=fields.get("topics", '["ИИ"]'),
        tags=fields.get("tags", '["#ии"]'),
        post_url=f"https://t.me/chan{n}/{n}",
    )
    session.add(nc)
    session.flush()

    tc = TrendCase(
        news_card_id=nc.id,
        trend_name=fields.get("trend_name", "Тренд"),
        case_title=fields.get("case_title", "Кейс"),
        company=fields.get("company"),
        description=fields.get("description", ""),
        value=fields.get("value"),
        how_it_works=fields.get("how_it_works"),
        market=fields.get("market", "Россия"),
    )
    session.add(tc)
    session.flush()
    return tc.id


def test_search_substring_in_word(search_db):
    """'цифр' находит 'цифровой'."""
    with _db_base.get_session() as s:
        _add_case(s, case_title="Запуск цифрового рубля")
    _, total = _search_cases(query="цифр")
    assert total == 1


def test_search_substring_prefix(search_db):
    """'банк' находит 'банкомат', 'Сбербанк'."""
    with _db_base.get_session() as s:
        _add_case(s, case_title="Новый банкомат Сбербанка")
    _, total = _search_cases(query="банк")
    assert total == 1


def test_search_case_insensitive(search_db):
    """Регистр не важен."""
    with _db_base.get_session() as s:
        _add_case(s, case_title="Биометрия в банках")
    for q in ["биометрия", "БИОМЕТРИЯ", "Биометрия"]:
        _, total = _search_cases(query=q)
        assert total == 1, f"Не нашёл для {q!r}"


def test_search_in_how_it_works(search_db):
    """Поиск по полю how_it_works."""
    with _db_base.get_session() as s:
        _add_case(
            s,
            case_title="Новый продукт",
            how_it_works="Использует нейросеть для оценки кредитоспособности",
        )
    _, total = _search_cases(query="нейросеть")
    assert total == 1


def test_search_company_substring(search_db):
    """Поиск по компании с подстрокой."""
    with _db_base.get_session() as s:
        _add_case(s, company="Сбербанк")
    _, total = _search_cases(company="сбер")
    assert total == 1


def test_topic_in_topics_field(search_db):
    """Тема находится в поле topics."""
    with _db_base.get_session() as s:
        _add_case(s, topics='["ИИ", "Банки"]', tags='[]')
    _, total = _search_cases(topic="ИИ")
    assert total == 1


def test_topic_in_tags_field(search_db):
    """Тема находится в тегах."""
    with _db_base.get_session() as s:
        _add_case(s, topics='["Банки"]', tags='["#биометрия"]')
    _, total = _search_cases(topic="биометрия")
    assert total == 1


def test_topic_in_trend_name(search_db):
    """Тема находится в названии тренда."""
    with _db_base.get_session() as s:
        _add_case(s, topics='[]', tags='[]', trend_name="Биометрические платежи")
    _, total = _search_cases(topic="биометр")
    assert total == 1


def test_search_no_match(search_db):
    with _db_base.get_session() as s:
        _add_case(s, case_title="Совсем про другое")
    _, total = _search_cases(query="несуществующее")
    assert total == 0
