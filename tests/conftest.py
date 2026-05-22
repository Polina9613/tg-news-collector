from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.init_db import init_db
from db.models import RawPost, Source


@pytest.fixture(scope="session", autouse=True)
def ensure_schema():
    """Создаёт таблицы и применяет миграции к модульной БД перед тестами."""
    init_db()


@pytest.fixture()
def db_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(db_engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def sample_source(db_session):
    source = Source(
        username="test_channel",
        title="Test Channel",
        topics='["технологии"]',
        is_active=True,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


@pytest.fixture()
def sample_raw_post(db_session, sample_source):
    post = RawPost(
        source_id=sample_source.id,
        message_id=1001,
        channel_username="test_channel",
        post_url="https://t.me/test_channel/1001",
        raw_text="Центральный банк повысил ключевую ставку до 21%."
        " Решение вступает в силу немедленно.",
        published_at=datetime(2024, 1, 15, 10, 0, 0),
        has_media=False,
        is_forwarded=False,
    )
    db_session.add(post)
    db_session.commit()
    db_session.refresh(post)
    post.source  # eagerly load relationship
    return post


@pytest.fixture()
def sample_raw_post_empty(db_session, sample_source):
    post = RawPost(
        source_id=sample_source.id,
        message_id=1002,
        channel_username="test_channel",
        post_url="https://t.me/test_channel/1002",
        raw_text=None,
        published_at=datetime(2024, 1, 15, 11, 0, 0),
        has_media=True,
        is_forwarded=False,
    )
    db_session.add(post)
    db_session.commit()
    db_session.refresh(post)
    return post
