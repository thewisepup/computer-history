import os
from pathlib import Path

import live_data_guard  # noqa: F401
import pytest
from fake_host import FakeHost
from hypothesis import HealthCheck, settings

from computer_history.cli import app as cli_app
from computer_history.host import NOTIFY_ENV_VAR
from computer_history.logs import LOG_DIR_ENV_VAR, LOG_LEVEL_ENV_VAR
from computer_history.logs import reset as reset_logging
from computer_history.store import DB_ENV_VAR, connect
from computer_history.store import db as store_db
from computer_history.synthetic import CACHE_ENV_VAR

settings.register_profile(
    "deterministic",
    max_examples=300,
    derandomize=True,
    database=None,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "explore",
    settings.get_profile("deterministic"),
    max_examples=5000,
    derandomize=False,
    database=settings.get_profile("default").database,
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "deterministic"))

PERF_TESTS = Path(__file__).resolve().parent / "perf"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.path.resolve().is_relative_to(PERF_TESTS):
            item.add_marker("perf")


@pytest.fixture(autouse=True)
def no_db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DB_ENV_VAR, raising=False)


@pytest.fixture(autouse=True)
def no_live_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_app, "LiveHost", FakeHost)


@pytest.fixture(autouse=True)
def log_dir(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory):
    folder = tmp_path_factory.mktemp("logs")
    monkeypatch.setenv(LOG_DIR_ENV_VAR, str(folder))
    monkeypatch.setenv(NOTIFY_ENV_VAR, "0")
    monkeypatch.delenv(LOG_LEVEL_ENV_VAR, raising=False)
    yield folder
    reset_logging()


@pytest.fixture(autouse=True)
def dataset_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    folder = tmp_path_factory.mktemp("datasets")
    monkeypatch.setenv(CACHE_ENV_VAR, str(folder))
    return folder


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
