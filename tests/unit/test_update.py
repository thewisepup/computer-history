from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli_output import STATUS, UNREACHABLE_AW, RunCli, section
from db_states import SUPPORTED, newer_db, stored_ids, user_version, writer
from fake_aw import FakeAW
from fake_host import (
    BackendStart,
    FakeHost,
    completes_a_cycle,
    crashes,
    gate_runs,
    installed_package,
    stays_silent,
)

from computer_history.cli import ingest as cli_ingest
from computer_history.host import CheckOutcome
from computer_history.sources import backend_heartbeat_path, runner
from computer_history.stable import (
    BACKEND,
    BACKUPS_FOLDER_NAME,
    PRE_UPDATE_FOLDER_NAME,
    Layout,
    stable_layout,
    version_name,
)
from computer_history.stable import updates as stable_update
from computer_history.store import DATABASE_NAME, spool_hold_path

OLDEST = "a" * 40
OLDER = "b" * 40
NEWER = "c" * 40
NEWEST = "d" * 40
INSTALL = "Stable install:"
CYCLE_ERROR = "aw-window: ActivityWatch unreachable"
SPOOL_FILE = "20261120T120000.000000Z.jsonl"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "spool" / "records.jsonl"
CAPTURE = next(line for line in FIXTURE.read_text().splitlines() if '"kind":"capture"' in line)
CAPTURE_ID = json.loads(CAPTURE)["id"]


@pytest.fixture(autouse=True)
def quick_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stable_update, "FIRST_CYCLE_POLL_SECONDS", 0.001)
    monkeypatch.setattr(stable_update, "FIRST_CYCLE_WAIT_SECONDS", 0.05)


@pytest.fixture
def layout(run: RunCli, live: Path, checkout: Path) -> Layout:
    """A stable install of OLDER over a live database holding two windows."""
    with writer(live / DATABASE_NAME, "a", "b"):
        pass
    assert run(checkout, "install", host=FakeHost(checks={OLDER: gate_runs()}))[0] == 0
    return stable_layout()


def stable_code(layout: Layout) -> Path:
    return installed_package(layout.current.resolve() / "venv")


def heartbeat(layout: Layout) -> Path:
    return backend_heartbeat_path(layout.live / DATABASE_NAME)


def updating(layout: Layout, *starts: BackendStart, **options: object) -> FakeHost:
    """main with NEWER passing over the installed OLDER, the backend's starts scripted."""
    return FakeHost(
        checks={NEWER: gate_runs(), OLDER: gate_runs()},
        loaded=[BACKEND.label],
        backend_starts=starts,
        **options,  # type: ignore[arg-type]
    )


def install_state(layout: Layout) -> dict[Path, bytes | str]:
    """Every file and link of the live folder and the LaunchAgents, links by where they point."""
    found: dict[Path, bytes | str] = {}
    for folder in (layout.live, layout.launch_agents):
        for path in folder.rglob("*"):
            if path.is_symlink():
                found[path] = str(path.readlink())
            elif path.is_file():
                found[path] = path.read_bytes()
    return found


def pre_update_backups(layout: Layout) -> list[Path]:
    return sorted((layout.live / BACKUPS_FOLDER_NAME / PRE_UPDATE_FOLDER_NAME).glob("*.db"))


def log_lines(layout: Layout) -> list[dict[str, object]]:
    return [json.loads(line) for line in layout.update_log.read_text().splitlines()]


def restarted(host: FakeHost) -> set[str]:
    return {label for call, label in host.calls if call in ("load", "unload")}


def changes(host: FakeHost) -> list[tuple[str, str]]:
    return [(call, label) for call, label in host.calls if call in ("build", "load", "unload")]


def test_update_is_a_no_op_when_the_newest_passing_commit_is_current(
    run: RunCli, layout: Layout
) -> None:
    host = FakeHost(checks={NEWER: gate_runs(unit=CheckOutcome.FAILURE), OLDER: gate_runs()})
    before = install_state(layout)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert out[0] == f"Profile stable (version {version_name(OLDER)}), stable install {layout.live}"
    assert out[1:] == [f"Already up to date: version {version_name(OLDER)} is current"]
    assert install_state(layout) == before
    assert changes(host) == []


def test_update_backs_up_switches_and_keeps_the_old_version_once_the_first_cycle_completes(
    run: RunCli, layout: Layout
) -> None:
    backed_up_at_start: list[list[Path]] = []

    def new_backend(host: FakeHost) -> None:
        backed_up_at_start.append(pre_update_backups(layout))
        completes_a_cycle(heartbeat(layout))(host)

    host = updating(layout, new_backend)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    new, old = version_name(NEWER), version_name(OLDER)
    (backup,) = pre_update_backups(layout)
    assert backed_up_at_start == [[backup]]
    assert stored_ids(backup) == ["a", "b"]
    assert layout.current.resolve() == layout.versions / new
    assert layout.previous.resolve() == layout.versions / old
    assert sorted(path.name for path in layout.versions.iterdir()) == [old, new]
    assert not spool_hold_path(layout.live / DATABASE_NAME).exists()
    assert host.calls.index(("unload", BACKEND.label)) < host.calls.index(("load", BACKEND.label))
    assert restarted(host) == {BACKEND.label}
    assert host.notifications == []
    assert out[1:] == [
        "Release gate: lint, unit, data, poc, secrets, macos-capture-agent-tests,"
        " macos-capture-agent-e2e",
        f"Updated to version {new} (commit {NEWER}) from {old}",
        f"  backup        {backup} (schema v{SUPPORTED})",
        "  first cycle   completed; the backend deletes stored spool files again",
        f"  current       {layout.current} -> {layout.versions / new}",
        f"  previous      {old} (rollback returns to it)",
    ]
    ((entry),) = log_lines(layout)
    assert {k: entry[k] for k in ("action", "from", "to", "reason")} == {
        "action": "updated",
        "from": old,
        "to": new,
        "reason": None,
    }

    _, out, _ = run(stable_code(layout), *STATUS, host=host)
    last = section(out, INSTALL)[-1]
    assert last.startswith(f"  last update   updated {old} -> {new}, ")
    assert last.endswith(" ago)")


def test_a_second_update_keeps_one_previous_version(run: RunCli, layout: Layout) -> None:
    host = updating(layout, completes_a_cycle(heartbeat(layout)))
    assert run(stable_code(layout), "update", host=host)[0] == 0
    host = FakeHost(
        checks={NEWEST: gate_runs(), NEWER: gate_runs()},
        loaded=[BACKEND.label],
        backend_starts=[completes_a_cycle(heartbeat(layout))],
    )

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    names = [version_name(commit) for commit in (NEWER, NEWEST)]
    assert sorted(path.name for path in layout.versions.iterdir()) == names
    assert (
        f"  removed       {layout.versions / version_name(OLDER)} (one previous version is kept)"
        in out
    )


@pytest.mark.parametrize(
    "newest",
    [
        {"unit": CheckOutcome.FAILURE},
        {"lint": None},
        {"macos-capture-agent-e2e": CheckOutcome.RUNNING},
        {"secrets": CheckOutcome.CANCELLED},
    ],
    ids=["failed", "missing", "running", "cancelled"],
)
def test_update_skips_commits_the_release_gate_does_not_pass(
    run: RunCli, layout: Layout, newest: dict[str, CheckOutcome | None]
) -> None:
    host = FakeHost(
        checks={NEWEST: gate_runs(**newest), NEWER: gate_runs(), OLDER: gate_runs()},
        backend_starts=[completes_a_cycle(heartbeat(layout))],
    )

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert layout.current.resolve().name == version_name(NEWER)
    ((check, outcome),) = newest.items()
    reason = "missing" if outcome is None else outcome.value
    assert f"  skipped {version_name(NEWEST)}: {check} {reason}" in out


def test_update_ignores_the_checks_outside_the_release_gate(run: RunCli, layout: Layout) -> None:
    runs = gate_runs(typecheck=CheckOutcome.FAILURE, perf=CheckOutcome.RUNNING)
    host = FakeHost(
        checks={NEWER: runs, OLDER: gate_runs()},
        backend_starts=[completes_a_cycle(heartbeat(layout))],
    )

    assert run(stable_code(layout), "update", host=host)[0] == 0

    assert layout.current.resolve().name == version_name(NEWER)


@pytest.mark.parametrize(
    "host_options",
    [
        {"build_error": "could not install commit: resolution failed"},
        {"build_error": "could not run the built command: ImportError: no module named x"},
        {"offline": True},
    ],
    ids=["build fails", "smoke fails", "offline"],
)
def test_an_update_that_fails_before_switching_changes_nothing(
    run: RunCli, layout: Layout, host_options: dict[str, object]
) -> None:
    host = updating(layout, **host_options)
    before = install_state(layout)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 1
    assert out[1:] == []
    assert err.startswith("update failed: ")
    assert err.rstrip().endswith("(nothing was changed)")
    assert install_state(layout) == before
    assert [call for call in changes(host) if call[0] != "build"] == []


def test_an_update_whose_backup_fails_changes_nothing_and_restarts_the_backend(
    run: RunCli, layout: Layout
) -> None:
    host = updating(layout)
    backups = layout.live / BACKUPS_FOLDER_NAME / PRE_UPDATE_FOLDER_NAME
    backups.parent.mkdir(parents=True)
    backups.write_text("a file where the folder goes\n")
    before = install_state(layout)

    code, _, err = run(stable_code(layout), "update", host=host)

    assert code == 1
    assert err.startswith("update failed: ")
    assert err.rstrip().endswith("(nothing was changed)")
    assert install_state(layout) == before
    assert host.jobs[BACKEND.label].loaded


@pytest.mark.parametrize(
    ("start", "reason"),
    [
        (crashes, "the backend crashed before its first ingest cycle completed"),
        (None, f"its first ingest cycle failed: {CYCLE_ERROR}"),
        (stays_silent, "no ingest cycle completed within 0.05s"),
    ],
    ids=["crash", "failed cycle", "timeout"],
)
def test_update_falls_back_on_its_own_and_keeps_the_database_when_the_schema_is_unchanged(
    run: RunCli, layout: Layout, start: BackendStart | None, reason: str
) -> None:
    host = updating(layout, start or completes_a_cycle(heartbeat(layout), error=CYCLE_ERROR))
    before = {path: data for path, data in install_state(layout).items() if path.is_symlink()}

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 1, err
    new, old = version_name(NEWER), version_name(OLDER)
    assert {path: data for path, data in install_state(layout).items() if path.is_symlink()} == (
        before
    )
    assert sorted(path.name for path in layout.versions.iterdir()) == [old]
    assert not spool_hold_path(layout.live / DATABASE_NAME).exists()
    assert host.jobs[BACKEND.label].loaded
    assert restarted(host) == {BACKEND.label}
    assert [call for call in host.calls if call[1] == BACKEND.label][-1] == ("load", BACKEND.label)
    assert out[2] == f"Update to version {new} fell back to {old}: {reason}"
    assert out[4:] == [
        "  database      kept as it is (the schema did not change)",
        f"  backend       restarted on {old}; it reads the spool files it kept again",
    ]
    assert host.notifications == [
        ("Computer History update fell back", f"Version {new} {reason}; back on {old}.")
    ]
    ((entry),) = log_lines(layout)
    assert {k: entry[k] for k in ("action", "from", "to", "reason")} == {
        "action": "fell back",
        "from": new,
        "to": old,
        "reason": reason,
    }

    _, out, _ = run(stable_code(layout), *STATUS, host=host)
    last = section(out, INSTALL)[-1]
    assert last.startswith(f"  last update   fell back {new} -> {old}, ")
    assert last.endswith(f" ago): {reason}")


def test_a_fallback_after_the_new_version_changed_the_schema_restores_the_backup(
    run: RunCli, layout: Layout
) -> None:
    database = layout.live / DATABASE_NAME

    def migrates_then_fails(host: FakeHost) -> None:
        with writer(database, "written by the new version"):
            pass
        newer_db(database)
        completes_a_cycle(heartbeat(layout), error=CYCLE_ERROR)(host)

    host = updating(layout, migrates_then_fails)

    code, out, _ = run(stable_code(layout), "update", host=host)

    assert code == 1
    (backup,) = pre_update_backups(layout)
    assert user_version(database) == SUPPORTED
    assert stored_ids(database) == ["a", "b"]
    assert out[4] == f"  restored      {backup} (the new version changed the schema)"
    assert host.jobs[BACKEND.label].loaded


def test_a_fallback_whose_notification_fails_still_falls_back_and_says_so(
    run: RunCli, layout: Layout
) -> None:
    host = updating(layout, crashes, notify_error="could not post a notification: denied")

    code, out, _ = run(stable_code(layout), "update", host=host)

    assert code == 1
    assert layout.current.resolve().name == version_name(OLDER)
    assert out[-1] == (
        "  warning: the notification could not be posted: could not post a notification: denied"
    )


def test_rollback_swaps_current_and_previous_without_the_network(
    run: RunCli, layout: Layout
) -> None:
    assert (
        run(
            stable_code(layout),
            "update",
            host=updating(layout, completes_a_cycle(heartbeat(layout))),
        )[0]
        == 0
    )
    host = FakeHost(offline=True, loaded=[BACKEND.label])
    new, old = version_name(NEWER), version_name(OLDER)

    code, out, err = run(stable_code(layout), "rollback", host=host)

    assert code == 0, err
    assert layout.current.resolve() == layout.versions / old
    assert layout.previous.resolve() == layout.versions / new
    assert ("main_commits", "20") not in host.calls
    assert restarted(host) == {BACKEND.label}
    assert host.calls.index(("unload", BACKEND.label)) < host.calls.index(("load", BACKEND.label))
    assert out[1:] == [
        f"Rolled back to version {old} from {new}",
        f"  previous      {new} (rollback again returns to it)",
        "  backend       restarted",
    ]
    assert log_lines(layout)[-1]["action"] == "rolled back"
    _, out, _ = run(stable_code(layout), *STATUS, host=host)
    assert section(out, INSTALL)[-1].startswith(f"  last update   rolled back {new} -> {old}, ")


def test_rollback_with_no_previous_version_changes_nothing(run: RunCli, layout: Layout) -> None:
    host = FakeHost(loaded=[BACKEND.label])
    before = install_state(layout)

    code, _, err = run(stable_code(layout), "rollback", host=host)

    assert code == 1
    assert (
        err
        == "rollback failed: there is no previous version to roll back to (nothing was changed)\n"
    )
    assert install_state(layout) == before
    assert changes(host) == []


@pytest.fixture
def spool(live: Path) -> Path:
    folder = live / "spool"
    folder.mkdir()
    (folder / SPOOL_FILE).write_text(CAPTURE + "\n")
    return folder


@pytest.fixture
def cycles(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Let ingest --watch run as many cycles as the list's one item says, then stop it."""
    left = [1]

    def next_cycle(_: float) -> None:
        left[0] -= 1
        if left[0] <= 0:
            raise KeyboardInterrupt

    monkeypatch.setattr(runner.time, "sleep", next_cycle)
    return left


@pytest.fixture
def aw_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_ingest, "AWClient", lambda *args, **kwargs: FakeAW({}))


def test_the_backend_keeps_spool_files_until_its_first_cycle_completes(
    run: RunCli, layout: Layout, spool: Path, cycles: list[int], aw_up: None
) -> None:
    hold = spool_hold_path(layout.live / DATABASE_NAME)
    hold.write_text("")

    assert run(stable_code(layout), "ingest", "--watch", host=FakeHost())[0] == 0

    assert (spool / SPOOL_FILE).exists()
    assert not hold.exists()
    assert CAPTURE_ID in stored_ids(layout.live / DATABASE_NAME)

    cycles[0] = 1
    assert run(stable_code(layout), "ingest", "--watch", host=FakeHost())[0] == 0

    assert not (spool / SPOOL_FILE).exists()
    assert stored_ids(layout.live / DATABASE_NAME).count(CAPTURE_ID) == 1


def test_a_backend_whose_first_cycle_fails_keeps_holding(
    run: RunCli, layout: Layout, spool: Path, cycles: list[int]
) -> None:
    hold = spool_hold_path(layout.live / DATABASE_NAME)
    hold.write_text("")

    code = run(stable_code(layout), "ingest", "--watch", *UNREACHABLE_AW, host=FakeHost())[0]

    assert code == 0
    assert hold.exists()
    assert (spool / SPOOL_FILE).exists()


def test_held_spool_files_are_read_again_harmlessly_after_a_fallback(
    run: RunCli, layout: Layout, spool: Path, cycles: list[int]
) -> None:
    hold = spool_hold_path(layout.live / DATABASE_NAME)
    hold.write_text("")
    assert run(stable_code(layout), "ingest", "--watch", *UNREACHABLE_AW, host=FakeHost())[0] == 0
    hold.unlink()
    stored = stored_ids(layout.live / DATABASE_NAME)

    code, out, err = run(stable_code(layout), "ingest", *UNREACHABLE_AW, host=FakeHost())

    assert not (spool / SPOOL_FILE).exists()
    assert stored_ids(layout.live / DATABASE_NAME) == stored
    assert code == 1, err
    assert "  ax-text     inserted      0  skipped      1  held back   0" in out
