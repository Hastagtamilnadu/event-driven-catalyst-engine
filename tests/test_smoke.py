import sys
from pathlib import Path

from qual_event_engine.config import load_risk_config, load_strategy_book
from qual_event_engine.persistence.database import connect, initialise
from qual_event_engine.runtime import project_root
from qual_event_engine.settings import Settings


def test_python_version_is_3_11() -> None:
    assert sys.version_info[:2] == (3, 11), f"Expected Python 3.11, got {sys.version}"


def test_settings_and_directories(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "test.db",
        data_root=tmp_path / "data",
        archive_root=tmp_path / "archive",
        manual_drop_root=tmp_path / "drop",
        log_root=tmp_path / "logs",
        backup_root=tmp_path / "backups",
        gemini_api_key=None,
        gemini_model_id="gemini-3.1-flash-lite",
        gemini_timeout_seconds=45.0,
    )
    settings.ensure_directories()
    assert settings.data_root.exists()
    assert settings.archive_root.exists()
    assert settings.manual_drop_root.exists()
    assert settings.log_root.exists()
    assert settings.backup_root.exists()


def test_database_initialisation(tmp_path: Path) -> None:
    db = tmp_path / "smoke.db"
    initialise(db)
    with connect(db) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        assert cursor.fetchone()[0] == "ok"
        cursor.execute("PRAGMA foreign_keys")
        assert cursor.fetchone()[0] == 1


def test_configurations_load() -> None:
    root = project_root()
    strategies, strat_hash = load_strategy_book(root)
    assert len(strategies.strategies) > 0
    assert len(strat_hash) == 64
    risk, risk_hash = load_risk_config(root)
    assert risk.paper_nav_inr > 0
    assert len(risk_hash) == 64
