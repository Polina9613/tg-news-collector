"""Проверка что роль subscriber удалена."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import db.base as _db_base
from db.models import Base, BotUser
from bot.users import get_or_create_user


@pytest.fixture
def roles_db(monkeypatch):
    test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(_db_base, "engine", test_engine)
    monkeypatch.setattr(_db_base, "SessionLocal", TestSession)
    yield
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


def test_new_user_is_analyst(roles_db):
    user = get_or_create_user(
        telegram_id=123, username="test",
        first_name="Test", last_name=None,
    )
    assert user["role"] == "analyst"


def test_subscriptions_table_not_in_models():
    """Subscription модель удалена."""
    import db.models
    assert not hasattr(db.models, "Subscription")


def test_set_role_rejects_subscriber(roles_db):
    """set_role не принимает subscriber."""
    from bot.users import set_role
    get_or_create_user(telegram_id=456, username="u2", first_name="U", last_name=None)
    with pytest.raises(AssertionError):
        set_role(456, "subscriber")


def test_bot_user_default_role_is_analyst(roles_db):
    """Дефолтная роль в модели — analyst, не subscriber."""
    with _db_base.get_session() as s:
        u = BotUser(telegram_id=999, username="x", first_name="X", last_name=None)
        s.add(u)
        s.flush()
        assert u.role == "analyst"
