from pathlib import Path

import pytest

from computer_history.store import DB_ENV_VAR, connect
from computer_history.store import db as store_db


@pytest.fixture(autouse=True)
def no_db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DB_ENV_VAR, raising=False)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "history.db"


@pytest.fixture
def conn(db_path: Path):
    connection = connect(db_path)
    yield connection
    connection.close()


@pytest.fixture
def quick_busy_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_db, "BUSY_TIMEOUT_SECONDS", 0.05)
