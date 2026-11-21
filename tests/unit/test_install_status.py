from __future__ import annotations

import plistlib
from pathlib import Path

import pytest
from fake_aw import FakeAW
from fake_host import FakeHost, gate_runs

from computer_history import cli
from computer_history.cli import ingest as cli_ingest
from computer_history.sources import runner
from computer_history.stable import BACKEND, CAPTURE_AGENT_LABEL, STOPGAP_LABEL, stable_layout
from computer_history.store import SHORT_COMMIT_LENGTH

COMMIT = "b" * 40
UNREACHABLE_AW = ("--aw-url", "http://127.0.0.1:1/api/0")


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    monkeypatch.setenv("HOME", str(folder))
    return folder


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    code = tmp_path / "checkout" / "computer_history"
    code.mkdir(parents=True)
    return code


@pytest.fixture
def one_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner.time, "sleep", interrupt)


def run(
    capsys: pytest.CaptureFixture[str], code: Path, host: FakeHost, *argv: str
) -> tuple[int, list[str], str]:
    exit_code = cli.main(list(argv), code=code, host=host)
    captured = capsys.readouterr()
    return exit_code, captured.out.splitlines(), captured.err


def section(out: list[str], title: str) -> list[str]:
    start = out.index(title) + 1
    end = next((i for i in range(start, len(out)) if not out[i].startswith("  ")), len(out))
    return out[start:end]


def test_status_shows_the_backends_last_completed_cycle(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    home: Path,
    checkout: Path,
    one_cycle: None,
    db_path: Path,
) -> None:
    host = FakeHost()
    _, out, _ = run(capsys, checkout, host, "status", "--db-path", str(db_path), *UNREACHABLE_AW)
    assert section(out, "Backend:") == [
        "  last cycle    none yet (no heartbeat beside the database)"
    ]

    monkeypatch.setattr(cli_ingest, "AWClient", lambda *args, **kwargs: FakeAW({}))
    assert run(capsys, checkout, host, "ingest", "--watch", "--db-path", str(db_path))[0] == 0
    _, out, _ = run(capsys, checkout, host, "status", "--db-path", str(db_path), *UNREACHABLE_AW)

    (line,) = section(out, "Backend:")
    assert line.startswith("  last cycle    ")
    assert line.endswith(" ago), ok")


def test_a_failed_cycle_still_writes_the_heartbeat_and_status_says_it_failed(
    capsys: pytest.CaptureFixture[str], home: Path, checkout: Path, one_cycle: None, db_path: Path
) -> None:
    host = FakeHost()
    assert (
        run(
            capsys, checkout, host, "ingest", "--watch", "--db-path", str(db_path), *UNREACHABLE_AW
        )[0]
        == 0
    )

    _, out, _ = run(capsys, checkout, host, "status", "--db-path", str(db_path), *UNREACHABLE_AW)

    (line,) = section(out, "Backend:")
    assert line.endswith(" ago), failed")


def test_status_shows_the_install_and_its_launch_agents(
    capsys: pytest.CaptureFixture[str], home: Path, checkout: Path, db_path: Path
) -> None:
    host = FakeHost(checks={COMMIT: gate_runs()})
    assert run(capsys, checkout, host, "install")[0] == 0

    _, out, _ = run(capsys, checkout, host, "status", "--db-path", str(db_path), *UNREACHABLE_AW)

    install = section(out, "Install:")
    assert install[0] == "  this run      dev"
    assert install[1].startswith(f"  current       {COMMIT[:SHORT_COMMIT_LENGTH]}, installed ")
    assert install[2:] == ["  previous      none"]
    pid = host.jobs[BACKEND.label].pid
    assert section(out, "LaunchAgents:") == [
        f"  backend          loaded, running (pid {pid})  {BACKEND.label}",
        f"  capture agent    not installed  {CAPTURE_AGENT_LABEL}",
    ]


def test_status_before_install_flags_the_stopgap_backend(
    capsys: pytest.CaptureFixture[str], home: Path, checkout: Path, db_path: Path
) -> None:
    layout = stable_layout()
    layout.launch_agents.mkdir(parents=True)
    (layout.launch_agents / f"{STOPGAP_LABEL}.plist").write_bytes(
        plistlib.dumps({"Label": STOPGAP_LABEL})
    )
    host = FakeHost(loaded=[STOPGAP_LABEL])

    _, out, _ = run(capsys, checkout, host, "status", "--db-path", str(db_path), *UNREACHABLE_AW)

    assert section(out, "Install:")[1:] == ["  current       none", "  previous      none"]
    assert section(out, "LaunchAgents:") == [
        f"  backend          not installed  {BACKEND.label}",
        f"  capture agent    not installed  {CAPTURE_AGENT_LABEL}",
        f"  stopgap backend  loaded, running (pid 100)  {STOPGAP_LABEL}",
        "  warning: the stopgap backend still runs; `computer-history install` retires it",
    ]
    assert ("job", BACKEND.label) not in host.calls


def test_status_asks_launchd_only_about_installed_agents(
    capsys: pytest.CaptureFixture[str], home: Path, checkout: Path, db_path: Path
) -> None:
    host = FakeHost()

    run(capsys, checkout, host, "status", "--db-path", str(db_path), *UNREACHABLE_AW)

    assert host.calls == []
