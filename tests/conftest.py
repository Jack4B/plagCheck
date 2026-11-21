import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Każdy test dostaje własną bazę SQLite i katalog danych."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.sqlite3'}")
    monkeypatch.setenv("SEARCH_PROVIDER", "none")
    monkeypatch.setenv("WORKER_MODE", "cron")
    monkeypatch.delenv("ACCESS_KEY", raising=False)
    yield
