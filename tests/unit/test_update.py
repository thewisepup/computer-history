from __future__ import annotations

import fcntl
import json
import os
import signal
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
    stays_silent,
    then,
)
from stable_updates import (
    NEWER,
    NEWEST,
    OLDER,
    changes,
    health,
    install_older,
    install_state,
    log_lines,
    stable_code,
    updating,
)

from computer_history.cli import ingest as cli_ingest
from computer_history.host import CheckOutcome
from computer_history.sources import read_health, runner
from computer_history.stable import (
    BACKEND,
    BACKUPS_FOLDER_NAME,
    PRE_UPDATE_FOLDER_NAME,
    Layout,
    version_name,
)
from computer_history.stable.updates import preparing, waiting
from computer_history.store import spool_hold_path

INSTALL = "Stable install:"
CYCLE_ERROR = "database error: disk I/O error"
AW_DOWN = "aw-window: ActivityWatch unreachable at http://127.0.0.1:5600/api/0"
QUICK = ("--wait", "0.05")
SPOOL_FILE = "20261120T120000.000000Z.jsonl"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "spool" / "records.jsonl"
CAPTURE = next(line for line in FIXTURE.read_text().splitlines() if '"kind":"capture"' in line)
CAPTURE_ID = json.loads(CAPTURE)["id"]


@pytest.fixture(autouse=True)
def quick_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(waiting, "FIRST_CYCLE_POLL_SECONDS", 0.001)


@pytest.fixture
def layout(run: RunCli, live: Path, checkout: Path) -> Layout:
    return install_older(run, live, checkout)


def pre_update_backups(layout: Layout) -> list[Path]:
    return sorted((layout.live / BACKUPS_FOLDER_NAME / PRE_UPDATE_FOLDER_NAME).glob("*.db"))


def restarted(host: FakeHost) -> set[str]:
    return {label for call, label in host.calls if call in ("load", "unload")}


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
        completes_a_cycle(health(layout))(host)

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
    assert not spool_hold_path(layout.database).exists()
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
    host = updating(layout, completes_a_cycle(health(layout)))
    assert run(stable_code(layout), "update", host=host)[0] == 0
    host = FakeHost(
        checks={NEWEST: gate_runs(), NEWER: gate_runs()},
        loaded=[BACKEND.label],
        backend_starts=[completes_a_cycle(health(layout))],
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
        backend_starts=[completes_a_cycle(health(layout))],
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
        backend_starts=[completes_a_cycle(health(layout))],
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
        (crashes, "the backend crashed before its first ingest cycle"),
        (None, f"the backend's first ingest cycle failed: {CYCLE_ERROR}"),
        (stays_silent, "the backend completed no ingest cycle within 0.05s"),
    ],
    ids=["crash", "failed cycle", "timeout"],
)
def test_update_falls_back_on_its_own_and_keeps_the_database_when_the_schema_is_unchanged(
    run: RunCli, layout: Layout, start: BackendStart | None, reason: str
) -> None:
    host = updating(layout, start or completes_a_cycle(health(layout), error=CYCLE_ERROR))
    before = {path: data for path, data in install_state(layout).items() if path.is_symlink()}

    code, out, err = run(stable_code(layout), "update", *QUICK, host=host)

    assert code == 1, err
    new, old = version_name(NEWER), version_name(OLDER)
    assert {path: data for path, data in install_state(layout).items() if path.is_symlink()} == (
        before
    )
    assert sorted(path.name for path in layout.versions.iterdir()) == [old]
    assert not spool_hold_path(layout.database).exists()
    assert host.jobs[BACKEND.label].loaded
    assert restarted(host) == {BACKEND.label}
    assert [call for call in host.calls if call[1] == BACKEND.label][-1] == ("load", BACKEND.label)
    assert out[2] == f"Update to version {new} fell back: {reason}"
    assert out[4:] == [
        "  database      kept as it is (the schema did not change)",
        f"  backend       restarted on {old}; it reads the spool files it kept again",
    ]
    assert host.notifications == [f"Update to {new} fell back: {reason}; back on {old}."]
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
    database = layout.database

    def migrates_then_fails(host: FakeHost) -> None:
        with writer(database, "written by the new version"):
            pass
        newer_db(database)
        completes_a_cycle(health(layout), error=CYCLE_ERROR)(host)

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
            host=updating(layout, completes_a_cycle(health(layout))),
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
    hold = spool_hold_path(layout.database)
    hold.write_text("")

    assert run(stable_code(layout), "ingest", "--watch", host=FakeHost())[0] == 0

    assert (spool / SPOOL_FILE).exists()
    assert not hold.exists()
    assert CAPTURE_ID in stored_ids(layout.database)

    cycles[0] = 1
    assert run(stable_code(layout), "ingest", "--watch", host=FakeHost())[0] == 0

    assert not (spool / SPOOL_FILE).exists()
    assert stored_ids(layout.database).count(CAPTURE_ID) == 1


def test_a_backend_whose_first_cycle_fails_keeps_holding(
    run: RunCli, layout: Layout, spool: Path, cycles: list[int]
) -> None:
    hold = spool_hold_path(layout.database)
    hold.write_text("")

    code = run(stable_code(layout), "ingest", "--watch", *UNREACHABLE_AW, host=FakeHost())[0]

    assert code == 0
    assert hold.exists()
    assert (spool / SPOOL_FILE).exists()
    written = read_health(health(layout))
    assert written is not None
    assert written.sources_unavailable


def test_held_spool_files_are_read_again_harmlessly_after_a_fallback(
    run: RunCli, layout: Layout, spool: Path, cycles: list[int]
) -> None:
    hold = spool_hold_path(layout.database)
    hold.write_text("")
    assert run(stable_code(layout), "ingest", "--watch", *UNREACHABLE_AW, host=FakeHost())[0] == 0
    hold.unlink()
    stored = stored_ids(layout.database)

    code, out, err = run(stable_code(layout), "ingest", *UNREACHABLE_AW, host=FakeHost())

    assert not (spool / SPOOL_FILE).exists()
    assert stored_ids(layout.database) == stored
    assert code == 1, err
    assert "  ax-text     inserted      0  skipped      1  held back   0" in out


def test_update_with_no_stable_install_says_to_install(
    run: RunCli, live: Path, checkout: Path
) -> None:
    host = FakeHost(checks={NEWER: gate_runs()})

    code, _, err = run(checkout, "update", host=host)

    assert code == 1
    assert err == f"update failed: there is no stable install in {live}; run install first\n"
    assert changes(host) == []


@pytest.mark.parametrize(
    "line",
    ['{"at": "2026-11-20T17:22:03", "action": "updated", "from": "a", "to": "b"}', "not json"],
    ids=["naive time", "not json"],
)
def test_status_reports_an_unreadable_update_log(run: RunCli, layout: Layout, line: str) -> None:
    layout.update_log.write_text(line + "\n")

    _, out, _ = run(stable_code(layout), *STATUS, host=FakeHost())

    assert section(out, INSTALL)[-1] == (
        f"  last update   unreadable update log: the last line of {layout.update_log} is not an"
        " update log entry"
    )


def test_update_never_moves_back_to_an_older_commit(run: RunCli, layout: Layout) -> None:
    host = updating(layout, completes_a_cycle(health(layout)))
    assert run(stable_code(layout), "update", host=host)[0] == 0
    host = FakeHost(checks={NEWER: gate_runs(unit=CheckOutcome.CANCELLED), OLDER: gate_runs()})
    before = install_state(layout)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    new, old = version_name(NEWER), version_name(OLDER)
    assert out[1:] == [
        f"Already up to date: version {new} is current (the newest passing commit, {old}, is"
        " older than current)"
    ]
    assert install_state(layout) == before
    assert changes(host) == []


def test_a_first_cycle_with_activitywatch_down_is_waited_out(run: RunCli, layout: Layout) -> None:
    down = completes_a_cycle(health(layout), error=AW_DOWN, sources_unavailable=True)
    host = updating(layout, then(down, stays_silent, completes_a_cycle(health(layout))))

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert layout.current.resolve().name == version_name(NEWER)
    assert out[2].startswith(f"Updated to version {version_name(NEWER)} ")


def test_activitywatch_down_for_the_whole_wait_falls_back_and_says_so(
    run: RunCli, layout: Layout
) -> None:
    down = completes_a_cycle(health(layout), error=AW_DOWN, sources_unavailable=True)
    host = updating(layout, down)

    code, out, _ = run(stable_code(layout), "update", *QUICK, host=host)

    assert code == 1
    assert layout.current.resolve().name == version_name(OLDER)
    assert out[2] == (
        f"Update to version {version_name(NEWER)} fell back: the backend's sources stayed"
        f" unavailable for the whole 0.05s wait: {AW_DOWN}"
    )


def test_a_one_shot_ingest_during_the_hold_keeps_spool_files(
    run: RunCli, layout: Layout, spool: Path, aw_up: None
) -> None:
    hold = spool_hold_path(layout.database)
    hold.write_text("")

    code, out, err = run(stable_code(layout), "ingest", host=FakeHost())

    assert code == 0, err
    assert (spool / SPOOL_FILE).exists()
    assert hold.exists()
    assert CAPTURE_ID in stored_ids(layout.database)
    assert out[-1] == f"  spool files kept: {hold} holds their deletion while an update runs"


def test_a_fallback_that_cannot_stop_the_new_backend_keeps_its_folder(
    run: RunCli, layout: Layout
) -> None:
    def launchd_breaks(host: FakeHost) -> None:
        host.job_error = "could not ask launchd about it: launchctl timed out"

    host = updating(layout, launchd_breaks)

    code, out, _ = run(stable_code(layout), "update", host=host)

    assert code == 1
    new_folder = layout.versions / version_name(NEWER)
    assert (new_folder / "installed").is_file()
    assert layout.current.resolve().name == version_name(OLDER)
    assert "  warning: the new version's backend could not be confirmed stopped: could not ask" in (
        " ".join(out)
    )
    assert f"  warning: kept {new_folder}, since its backend or a pointer may still use it" in out
    hold = spool_hold_path(layout.database)
    assert hold.exists()
    assert (
        f"  warning: kept the spool hold {hold}, since the new backend may still run; the"
        " backend's next ok cycle removes it"
    ) in out


def test_a_fallback_that_cannot_point_current_back_keeps_the_new_version_runnable(
    run: RunCli, layout: Layout
) -> None:
    def blocks_the_pointer_then_crashes(host: FakeHost) -> None:
        staged = layout.live / ".current.new"
        staged.mkdir()
        (staged / "in the way").write_text("")
        crashes(host)

    host = updating(layout, blocks_the_pointer_then_crashes)

    code, out, _ = run(stable_code(layout), "update", host=host)

    assert code == 1
    new_folder = layout.versions / version_name(NEWER)
    assert layout.current.resolve() == new_folder
    assert (new_folder / "installed").is_file()
    assert any(
        line.startswith(f"  warning: current could not be pointed back at {version_name(OLDER)}: ")
        for line in out
    )
    assert f"  warning: kept {new_folder}, since its backend or a pointer may still use it" in out
    assert host.notifications[-1].endswith("run computer-history status to see where it is.")


def test_an_interrupted_wait_falls_back_and_exits_130(
    run: RunCli, layout: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(waiting.time, "sleep", interrupt)
    host = updating(layout, stays_silent)

    code, out, _ = run(stable_code(layout), "update", host=host)

    assert code == 130
    reason = "the update was interrupted before the backend's first ingest cycle"
    assert out[2] == f"Update to version {version_name(NEWER)} fell back: {reason}"
    assert layout.current.resolve().name == version_name(OLDER)
    assert log_lines(layout)[-1]["reason"] == reason
    assert host.jobs[BACKEND.label].loaded


def test_a_failure_after_the_backup_removes_it(run: RunCli, layout: Layout) -> None:
    spool_hold_path(layout.database).mkdir()
    host = updating(layout)
    before = install_state(layout)

    code, _, err = run(stable_code(layout), "update", host=host)

    assert code == 1
    assert err.rstrip().endswith("(nothing was changed)")
    assert pre_update_backups(layout) == []
    assert install_state(layout) == before
    assert host.jobs[BACKEND.label].loaded


def test_a_rollback_that_cannot_point_previous_keeps_current_on_the_newer_version(
    run: RunCli, layout: Layout
) -> None:
    host = updating(layout, completes_a_cycle(health(layout)))
    assert run(stable_code(layout), "update", host=host)[0] == 0
    staged = layout.live / ".previous.new"
    staged.mkdir()
    (staged / "in the way").write_text("")

    code, _, err = run(stable_code(layout), "rollback", host=FakeHost(loaded=[BACKEND.label]))

    assert code == 1
    assert err.startswith(f"rollback failed: could not point previous at {version_name(NEWER)}: ")
    assert err.rstrip().endswith(
        f"(current points at {version_name(NEWER)} again; nothing was changed)"
    )
    assert layout.current.resolve().name == version_name(NEWER)
    assert layout.previous.resolve().name == version_name(OLDER)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["ctrl-c", "sigterm"])
def test_an_interrupt_during_the_pre_update_backup_changes_nothing_and_restarts_the_backend(
    run: RunCli, layout: Layout, monkeypatch: pytest.MonkeyPatch, signum: signal.Signals
) -> None:
    def interrupted_backup(*args: object, **kwargs: object) -> None:
        os.kill(os.getpid(), signum)

    monkeypatch.setattr(preparing, "take_pre_update_backup", interrupted_backup)
    host = updating(layout)
    before = install_state(layout)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 130
    assert out[1:] == []
    assert err == "update interrupted before switching versions (nothing was changed)\n"
    assert install_state(layout) == before
    assert host.jobs[BACKEND.label].loaded


class InterruptedFallback(FakeHost):
    """A host whose second start of the backend, the fallback's, arrives with a Ctrl-C."""

    def __init__(self, **options: object) -> None:
        super().__init__(**options)  # type: ignore[arg-type]
        self.backend_loads = 0

    def load(self, plist: Path) -> None:
        super().load(plist)
        if plist.name == f"{BACKEND.label}.plist":
            self.backend_loads += 1
            if self.backend_loads == 2:
                os.kill(os.getpid(), signal.SIGINT)


def test_an_interrupt_during_a_fallback_lets_it_finish_then_exits_130(
    run: RunCli, layout: Layout
) -> None:
    host = InterruptedFallback(
        checks={NEWER: gate_runs(), OLDER: gate_runs()},
        loaded=[BACKEND.label],
        backend_starts=[crashes],
    )

    code, out, _ = run(stable_code(layout), "update", host=host)

    assert code == 130
    assert out[2].startswith(f"Update to version {version_name(NEWER)} fell back: ")
    assert layout.current.resolve().name == version_name(OLDER)
    assert sorted(path.name for path in layout.versions.iterdir()) == [version_name(OLDER)]
    assert log_lines(layout)[-1]["action"] == "fell back"
    assert len(host.notifications) == 1
    assert host.jobs[BACKEND.label].loaded


def test_rollback_refuses_a_database_the_previous_version_cannot_open(
    run: RunCli, layout: Layout
) -> None:
    def migrates(host: FakeHost) -> None:
        newer_db(layout.database)
        completes_a_cycle(health(layout))(host)

    assert run(stable_code(layout), "update", host=updating(layout, migrates))[0] == 0
    (backup,) = pre_update_backups(layout)
    host = FakeHost(loaded=[BACKEND.label])
    before = install_state(layout)

    code, _, err = run(stable_code(layout), "rollback", host=host)

    assert code == 1
    assert err == (
        f"rollback failed: the database is at schema v{SUPPORTED + 1}, newer than version"
        f" {version_name(OLDER)} can open (v{SUPPORTED}); put its pre-update backup back first"
        f" with `computer-history restore {backup}`, then roll back (nothing was changed)\n"
    )
    assert install_state(layout) == before
    assert changes(host) == []


@pytest.mark.parametrize(
    "argv",
    [("install",), ("uninstall",), ("update",), ("rollback",), ("restore", "2026-11-20")],
    ids=["install", "uninstall", "update", "rollback", "restore"],
)
def test_a_second_install_command_is_refused_while_one_holds_the_live_folder(
    run: RunCli, layout: Layout, argv: tuple[str, ...]
) -> None:
    host = updating(layout, completes_a_cycle(health(layout)))
    before = install_state(layout)
    held = os.open(layout.live, os.O_RDONLY)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code, out, err = run(stable_code(layout), *argv, host=host)
    finally:
        os.close(held)

    assert code == 1
    assert out[1:] == []
    assert err == (
        f"{argv[0]} refused: another install, uninstall, update, rollback or restore is using"
        f" {layout.live}; run it again once that one has finished\n"
    )
    assert install_state(layout) == before
    assert changes(host) == []
