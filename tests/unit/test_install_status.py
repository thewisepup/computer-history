from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli_output import STATUS, UNREACHABLE_AW, RunCli, section
from fake_aw import FakeAW
from fake_host import FakeHost, gate_runs, installed_package, write_stopgap_plist

from computer_history.cli import ingest as cli_ingest
from computer_history.sources import backend_heartbeat_path, runner
from computer_history.stable import (
    BACKEND,
    CAPTURE_AGENT_LABEL,
    DAILY_BACKUP,
    STABLE_AGENTS,
    STOPGAP_LABEL,
    stable_layout,
    version_name,
)
from computer_history.store import DATABASE_NAME

COMMIT = "b" * 40
INSTALL = "Stable install:"
AGENTS = "Stable install's LaunchAgents:"
BACKEND_SECTION = "Stable backend:"


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


def test_dev_status_shows_the_stable_backends_last_cycle(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    live: Path,
    checkout: Path,
    stable_code: tuple[Path, FakeHost],
    one_cycle: None,
) -> None:
    code, host = stable_code
    heartbeat = backend_heartbeat_path(live / DATABASE_NAME)
    _, out, _ = run(checkout, *STATUS, host=host)
    assert section(out, BACKEND_SECTION) == [
        f"  last cycle    none yet (no heartbeat at {heartbeat})"
    ]

    monkeypatch.setattr(cli_ingest, "AWClient", lambda *args, **kwargs: FakeAW({}))
    assert run(code, "ingest", "--watch", host=host)[0] == 0
    _, out, _ = run(checkout, *STATUS, host=host)

    (line,) = section(out, BACKEND_SECTION)
    assert line.startswith("  last cycle    ")
    assert line.endswith(" ago), ok")


def test_a_failed_cycle_still_writes_the_heartbeat_and_status_says_it_failed(
    run: RunCli,
    checkout: Path,
    stable_code: tuple[Path, FakeHost],
    one_cycle: None,
) -> None:
    code, host = stable_code
    assert run(code, "ingest", "--watch", *UNREACHABLE_AW, host=host)[0] == 0

    _, out, _ = run(checkout, *STATUS, host=host)

    (line,) = section(out, BACKEND_SECTION)
    assert line.endswith(" ago), failed")


def test_a_dev_backends_heartbeat_is_not_shown_as_stables(
    run: RunCli,
    live: Path,
    dev: Path,
    checkout: Path,
    one_cycle: None,
) -> None:
    host = FakeHost()
    assert run(checkout, "ingest", "--watch", *UNREACHABLE_AW, host=host)[0] == 0
    assert backend_heartbeat_path(dev / DATABASE_NAME).is_file()

    _, out, _ = run(checkout, *STATUS, host=host)

    (line,) = section(out, BACKEND_SECTION)
    assert line.startswith("  last cycle    none yet")


@pytest.mark.parametrize(
    "written",
    [
        {"cycle_at": "2026-11-20T17:22:03", "ok": True},
        {"cycle_at": "2026-11-20T17:22:03+00:00", "ok": "yes"},
        {"ok": True},
    ],
    ids=["naive time", "ok not a bool", "no time"],
)
def test_an_unreadable_heartbeat_is_reported_not_trusted(
    run: RunCli, live: Path, checkout: Path, written: dict[str, object]
) -> None:
    backend_heartbeat_path(live / DATABASE_NAME).write_text(json.dumps(written))

    code, out, _ = run(checkout, *STATUS, host=FakeHost())

    assert code == 0
    (line,) = section(out, BACKEND_SECTION)
    assert line.startswith("  last cycle    unreadable heartbeat: ")


def test_status_shows_the_install_and_its_launch_agents(
    run: RunCli, checkout: Path, stable_code: tuple[Path, FakeHost]
) -> None:
    _, host = stable_code

    _, out, _ = run(checkout, *STATUS, host=host)

    install = section(out, INSTALL)
    assert install[0] == "  this run      dev"
    assert install[1].startswith(f"  current       {version_name(COMMIT)}, installed ")
    assert install[2:] == ["  previous      none"]
    pid = host.jobs[BACKEND.label].pid
    backup_pid = host.jobs[DAILY_BACKUP.label].pid
    assert section(out, AGENTS) == [
        f"  backend          loaded, running (pid {pid})  {BACKEND.label}",
        f"  backup           loaded, running (pid {backup_pid})  {DAILY_BACKUP.label}",
        f"  capture agent    not installed  {CAPTURE_AGENT_LABEL}",
    ]


def test_status_before_install_flags_the_stopgap_backend(
    run: RunCli, live: Path, checkout: Path
) -> None:
    write_stopgap_plist(stable_layout())
    host = FakeHost(loaded=[STOPGAP_LABEL])

    _, out, _ = run(checkout, *STATUS, host=host)

    assert section(out, INSTALL)[1:] == ["  current       none", "  previous      none"]
    assert section(out, AGENTS) == [
        f"  backend          not installed  {BACKEND.label}",
        f"  backup           not installed  {DAILY_BACKUP.label}",
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
