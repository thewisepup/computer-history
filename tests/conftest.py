from pathlib import Path

import pytest

from computer_history.store import DB_ENV_VAR, connect


@pytest.fixture(autouse=True)
def no_db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Never let a developer's $COMPUTER_HISTORY_DB leak into tests.
    monkeypatch.delenv(DB_ENV_VAR, raising=False)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "history.db"


@pytest.fixture
def conn(db_path: Path):
    connection = connect(db_path)
    yield connection
    connection.close()
