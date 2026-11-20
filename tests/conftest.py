import os
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

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

HOOK_BUDGET_ENV_VAR = "COMPUTER_HISTORY_HOOK_BUDGET"
HOOK_TEST_SECONDS = 3.0
HOOK_TOTAL_SECONDS = 15.0
HOOK_LEAVES_OUT = ("perf", "dataset")
_hook_seconds: dict[str, float] = {}


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not os.environ.get(HOOK_BUDGET_ENV_VAR) or report.when == "teardown":
        return
    if any(marker in report.keywords for marker in HOOK_LEAVES_OUT):
        return
    _hook_seconds[report.nodeid] = _hook_seconds.get(report.nodeid, 0.0) + report.duration


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not os.environ.get(HOOK_BUDGET_ENV_VAR):
        return
    slow = sorted(
        ((seconds, test) for test, seconds in _hook_seconds.items() if seconds > HOOK_TEST_SECONDS),
        reverse=True,
    )
    total = sum(_hook_seconds.values())
    if not slow and total <= HOOK_TOTAL_SECONDS:
        return
    write = session.config.get_terminal_writer().line
    write("")
    write(
        f"The pre-commit hook's tests took {total:.1f}s (budget {HOOK_TOTAL_SECONDS:g}s);"
        f" {len(slow)} took over {HOOK_TEST_SECONDS:g}s. Make each faster, or give its file"
        " `pytestmark = pytest.mark.dataset` so only CI runs it (docs/agents/checks.md):"
    )
    for seconds, test in slow:
        write(f"  {seconds:.1f}s  {test}")
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def no_db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DB_ENV_VAR, raising=False)


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
