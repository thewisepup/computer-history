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


def _runner_factor() -> float:
    """How much slower than a laptop this machine runs; 0 leaves the budget off."""
    return float(os.environ.get(HOOK_BUDGET_ENV_VAR) or 0)


def _over_budget() -> tuple[float, list[tuple[float, str]]]:
    factor = _runner_factor()
    total = sum(_hook_seconds.values())
    slow = sorted(
        (
            (seconds, test)
            for test, seconds in _hook_seconds.items()
            if seconds > HOOK_TEST_SECONDS * factor
        ),
        reverse=True,
    )
    return total, slow


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    report = yield
    hook_runs_it = not any(item.get_closest_marker(name) for name in HOOK_LEAVES_OUT)
    if _runner_factor() and call.when != "teardown" and hook_runs_it:
        _hook_seconds[item.nodeid] = _hook_seconds.get(item.nodeid, 0.0) + report.duration
    return report


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    factor = _runner_factor()
    if not factor or session.exitstatus != pytest.ExitCode.OK:
        return
    total, slow = _over_budget()
    if slow or total > HOOK_TOTAL_SECONDS * factor:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    factor = _runner_factor()
    if not factor:
        return
    total, slow = _over_budget()
    if not slow and total <= HOOK_TOTAL_SECONDS * factor:
        return
    terminalreporter.section("pre-commit hook budget", red=True)
    terminalreporter.line(
        f"The tests the pre-commit hook runs took {total:.1f}s, over"
        f" {HOOK_TOTAL_SECONDS * factor:g}s, or {len(slow)} took over"
        f" {HOOK_TEST_SECONDS * factor:g}s each (the laptop budget times {factor:g})."
        " Make each faster, or give its file `pytestmark = pytest.mark.dataset`"
        " so only CI runs it (docs/agents/checks.md):"
    )
    for seconds, test in slow:
        terminalreporter.line(f"  {seconds:.1f}s  {test}")


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
