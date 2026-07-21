from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest


def test_generate_dynamics_no_past_snapshots():
    from digest.llm_digest import generate_dynamics_section
    provider = MagicMock()
    result = generate_dynamics_section(provider, [], [], [])
    assert result == []
    provider._call.assert_not_called()


def test_generate_dynamics_with_past_data():
    from digest.llm_digest import generate_dynamics_section
    provider = MagicMock()
    provider._call.return_value = '{"dynamics_points": ["Крипто-банкинг: было 3 банка, стало 4."]}'

    past = [{
        "period_label": "01.07–07.07",
        "compact_case_index": [{"company": "Т-Банк", "topic": "Крипто", "title": "депозитарий"}],
        "overall_conclusions": ["Банки готовятся к крипте"],
    }]
    current = [{"company": "Альфа-Банк", "topic": "Крипто", "title": "крипто-платежи"}]

    result = generate_dynamics_section(provider, current, ["Альфа тоже в крипте"], past)
    assert len(result) == 1
    assert "Крипто-банкинг" in result[0]


def test_generate_dynamics_parse_error_returns_empty():
    from digest.llm_digest import generate_dynamics_section
    provider = MagicMock()
    provider._call.return_value = "not valid json"
    result = generate_dynamics_section(
        provider,
        [{"company": "X", "topic": "Y", "title": "Z"}],
        [],
        [{"period_label": "01.07", "compact_case_index": [], "overall_conclusions": []}],
    )
    assert result == []


def test_save_and_load_weekly_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import db.base
    from db.base import init_engine
    from db.models import Base
    init_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(db.base.engine)

    from digest.generator import _load_past_snapshots, _save_weekly_snapshot

    period_start = datetime.utcnow() - timedelta(days=14)
    period_end = datetime.utcnow() - timedelta(days=7)

    analysis = {
        "main_summary": "Тестовое главное",
        "overall_conclusions": ["Вывод 1"],
    }
    topics = {
        "Тема1": [{"company": "Компания1", "case_title": "Кейс 1"}],
    }
    _save_weekly_snapshot(period_start, period_end, analysis, topics)

    loaded = _load_past_snapshots(before=datetime.utcnow(), limit=3)
    assert len(loaded) == 1
    assert loaded[0]["compact_case_index"][0]["company"] == "Компания1"
    assert loaded[0]["overall_conclusions"] == ["Вывод 1"]


def test_no_snapshots_means_no_dynamics_call(tmp_path, monkeypatch):
    """Если снимков нет — generate_dynamics_section не должна вызываться в pipeline."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import db.base
    from db.base import init_engine
    from db.models import Base
    init_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(db.base.engine)

    from digest.generator import _load_past_snapshots
    result = _load_past_snapshots(before=datetime.utcnow(), limit=3)
    assert result == []
