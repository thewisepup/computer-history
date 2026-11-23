from __future__ import annotations

from pathlib import Path

import pytest
from cli_output import STATUS, UNREACHABLE_AW, RunCli, ingest_line, section
from fake_aw import FakeAW
from fake_host import FakeHost, gate_runs, installed_package, write_stopgap_plist

from computer_history.cli import ingest as cli_ingest
from computer_history.sources import health_path, read_health, runner
from computer_history.stable import (
    ACTIVITYWATCH_AT_LOGIN,
    BACKEND,
    CAPTURE_AGENT_LABEL,
    DAILY_BACKUP,
    STABLE_AGENTS,
    STOPGAP_LABEL,
    WATCHDOG,
    stable_layout,
    version_name,
)
from computer_history.store import DATABASE_NAME

COMMIT = "b" * 40
INSTALL = "Stable install:"
AGENTS = "Stable install's LaunchAgents:"


@pytest.fixture
def one_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner.time, "sleep", interrupt)


@pytest.fixture
def stable_code(run: RunCli, live: Path, checkout: Path) -> tuple[Path, FakeHost]:
    host = FakeHost(checks={COMMIT: gate_runs()})
    assert run(checkout, "install", host=host)[0] == 0
    return installed_package(stable_layout().link.resolve().parents[1]), host


def test_status_reads_the_backends_last_cycle_beside_the_database_it_was_given(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    live: Path,
    checkout: Path,
    stable_code: tuple[Path, FakeHost],
    one_cycle: None,
) -> None:
    code, host = stable_code
    monkeypatch.setattr(cli_ingest, "AWClient", lambda *args, **kwargs: FakeAW({}))
    assert run(code, "ingest", "--watch", host=host)[0] == 0

    _, stable_out, _ = run(code, *STATUS, host=host)
    _, dev_out, _ = run(checkout, *STATUS, host=host)

    assert ingest_line(stable_out).startswith("Ingest:        ok, last cycle ")
    assert ingest_line(dev_out) == "Ingest:        no `ingest --watch` has reported yet"
    assert not any(line.startswith("Stable backend") for line in stable_out + dev_out)


def test_a_failed_cycle_is_recorded_with_why_and_status_leads_with_it(
    run: RunCli,
    live: Path,
    stable_code: tuple[Path, FakeHost],
    one_cycle: None,
) -> None:
    code, host = stable_code
    assert run(code, "ingest", "--watch", *UNREACHABLE_AW, host=host)[0] == 0

    _, out, _ = run(code, *STATUS, host=host)

    health = read_health(health_path(live / DATABASE_NAME))
    assert health is not None and health.last_error is not None
    assert not health.ok and health.sources_unavailable
    assert "ActivityWatch" in health.last_error
    assert out[1].startswith("!! ingest is FAILING since ")
    assert out[1].endswith(health.last_error)
    assert "FAILING since" in ingest_line(out)


def test_status_shows_the_install_and_its_launch_agents(
    run: RunCli, checkout: Path, stable_code: tuple[Path, FakeHost]
) -> None:
    _, host = stable_code

    _, out, _ = run(checkout, *STATUS, host=host)

    install = section(out, INSTALL)
    assert install[0] == "  this run      dev"
    assert install[1].startswith(f"  current       {version_name(COMMIT)}, installed ")
    assert install[2:] == [
        "  previous      none",
        "  agent         built from unknown",
        "  last update   none yet",
    ]
    pids = {agent: host.jobs[agent.label].pid for agent in STABLE_AGENTS}
    assert section(out, AGENTS) == [
        f"  backend          loaded, running (pid {pids[BACKEND]})  {BACKEND.label}",
        f"  backup           loaded, running (pid {pids[DAILY_BACKUP]})  {DAILY_BACKUP.label}",
        f"  watchdog         loaded, running (pid {pids[WATCHDOG]})  {WATCHDOG.label}",
        f"  activitywatch    loaded, running (pid {pids[ACTIVITYWATCH_AT_LOGIN]})"
        f"  {ACTIVITYWATCH_AT_LOGIN.label}",
        f"  capture agent    not installed  {CAPTURE_AGENT_LABEL}",
    ]


def test_status_before_install_flags_the_stopgap_backend(
    run: RunCli, live: Path, checkout: Path
) -> None:
    write_stopgap_plist(stable_layout())
    host = FakeHost(loaded=[STOPGAP_LABEL])

    _, out, _ = run(checkout, *STATUS, host=host)

    assert section(out, INSTALL)[1:] == [
        "  current       none",
        "  previous      none",
        "  agent         built from unknown",
        "  last update   none yet",
    ]
    assert section(out, AGENTS) == [
        f"  backend          not installed  {BACKEND.label}",
        f"  backup           not installed  {DAILY_BACKUP.label}",
        f"  watchdog         not installed  {WATCHDOG.label}",
        f"  activitywatch    not installed  {ACTIVITYWATCH_AT_LOGIN.label}",
        f"  capture agent    not installed  {CAPTURE_AGENT_LABEL}",
        f"  stopgap backend  loaded, running (pid 100)  {STOPGAP_LABEL}",
        "  warning: the stopgap backend still runs; `computer-history install` retires it",
    ]
    assert ("job", BACKEND.label) not in host.calls


def test_status_finds_a_running_stopgap_whose_plist_was_deleted(
    run: RunCli, live: Path, checkout: Path
) -> None:
    host = FakeHost(loaded=[STOPGAP_LABEL])

    _, out, _ = run(checkout, *STATUS, host=host)

    capture_agent = len(STABLE_AGENTS) + 1
    assert section(out, AGENTS)[capture_agent:] == [
        f"  stopgap backend  loaded, running (pid 100), plist deleted  {STOPGAP_LABEL}",
        "  warning: the stopgap backend still runs; `computer-history install` retires it",
    ]


def test_status_survives_launchd_not_answering(
    run: RunCli, checkout: Path, stable_code: tuple[Path, FakeHost]
) -> None:
    _, host = stable_code
    host.job_error = "could not ask launchd about it: launchctl timed out"

    code, out, err = run(checkout, *STATUS, host=host)

    assert code == 0
    assert "Traceback" not in err
    assert section(out, AGENTS) == [f"  cannot ask launchd: {host.job_error}"]


def test_status_asks_launchd_nothing_without_a_live_folder_or_plists(
    run: RunCli, home: Path, checkout: Path, db_path: Path
) -> None:
    host = FakeHost()

    run(checkout, "status", "--db-path", str(db_path), *UNREACHABLE_AW, host=host)

    assert host.calls == []
