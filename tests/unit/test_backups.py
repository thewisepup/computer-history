from __future__ import annotations

import os
import plistlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from cli_output import RunCli
from db_states import damaged, left_with_a_wal, stored_ids, writer
from fake_host import FakeHost, gate_runs, installed_package

from computer_history.cli import backup as cli_backup
from computer_history.cli import status as cli_status
from computer_history.cli.formatting import human_size, when
from computer_history.sources import WINDOW_SOURCE
from computer_history.stable import (
    BACKEND,
    DAILY_BACKUP,
    DAILY_KEPT,
    stable_layout,
    take_pre_update_backup,
    version_name,
)
from computer_history.store import (
    DATABASE_NAME,
    connect,
    supported_version,
)

COMMIT = "b" * 40
NOON = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """The time the backup commands see; set its one item to move it."""
    now = [NOON]
    monkeypatch.setattr(cli_backup, "utc_now", lambda: now[0])
    monkeypatch.setattr(cli_status, "utc_now", lambda: now[0])
    return now


@pytest.fixture
def stable(run: RunCli, live: Path, checkout: Path) -> tuple[Path, FakeHost]:
    host = FakeHost(checks={COMMIT: gate_runs()})
    assert run(checkout, "install", host=host)[0] == 0
    return installed_package(stable_layout().link.resolve().parents[1]), host


def local_day(moment: datetime) -> date:
    return moment.astimezone().date()


def daily(live: Path, day: date) -> Path:
    return live / "backups" / "daily" / f"history-{day.isoformat()}.db"


def test_the_daily_backup_copies_what_the_live_database_committed_while_a_writer_holds_it(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "a", "b") as backend:
        backend.execute("BEGIN IMMEDIATE")
        backend.execute(
            "INSERT INTO observations (source, source_id, started_at, ended_at, payload,"
            " ingested_at) VALUES (?, 'uncommitted', '', '', '{}', '')",
            (WINDOW_SOURCE,),
        )

        exit_code, out, err = run(code, "backup", host=host)

        backend.execute("COMMIT")

    assert exit_code == 0, err
    copy = daily(live, local_day(NOON))
    assert out[0] == (
        f"Profile stable (version {version_name(COMMIT)}), database {live / DATABASE_NAME}"
    )
    assert out[1] == f"Backed up {live / DATABASE_NAME}"
    assert out[2] == f"  copied to {copy}"
    assert out[3].startswith(f"  schema v{supported_version()}, ")
    assert out[3].endswith(", integrity ok")
    assert stored_ids(copy) == ["a", "b"]


def test_the_daily_backup_keeps_the_newest_seven_days_and_leaves_other_files(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    connect(live / DATABASE_NAME).close()
    days = [local_day(NOON - timedelta(days=n)) for n in range(9, 0, -1)]
    for day in days:
        daily(live, day).parent.mkdir(parents=True, exist_ok=True)
        daily(live, day).write_text("an older backup\n")
    stray = daily(live, days[0]).with_name("notes.txt")
    stray.write_text("mine\n")

    exit_code, out, err = run(code, "backup", host=host)

    assert exit_code == 0, err
    kept = sorted(path.name for path in daily(live, days[0]).parent.glob("history-*.db"))
    assert kept == [daily(live, day).name for day in [*days[-6:], local_day(NOON)]]
    assert stray.is_file()
    assert out[4:] == [f"  removed   {daily(live, day)}" for day in days[:3]]


def test_a_second_run_on_the_same_day_keeps_the_days_first_backup(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "morning"):
        pass
    assert run(code, "backup", host=host)[0] == 0
    with writer(live / DATABASE_NAME, "evening"):
        pass
    clock[0] = NOON + timedelta(hours=3)

    exit_code, out, err = run(code, "backup", host=host)

    assert exit_code == 0, err
    assert out[1:] == [f"Today's backup is already taken: {daily(live, local_day(NOON))}"]
    assert stored_ids(daily(live, local_day(NOON))) == ["morning"]


def test_a_day_missed_with_the_lid_closed_is_taken_when_the_backup_next_runs(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    connect(live / DATABASE_NAME).close()
    assert run(code, "backup", host=host)[0] == 0
    clock[0] = NOON + timedelta(days=2, hours=7)

    exit_code, _, err = run(code, "backup", host=host)

    assert exit_code == 0, err
    folder = daily(live, local_day(NOON)).parent
    assert sorted(path.name for path in folder.iterdir()) == [
        daily(live, local_day(NOON)).name,
        daily(live, local_day(clock[0])).name,
    ]


def test_a_backup_with_no_database_yet_takes_nothing_and_succeeds(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable

    exit_code, out, err = run(code, "backup", host=host)

    assert exit_code == 0, err
    assert out[1:] == [f"No database at {live / DATABASE_NAME} yet: nothing to back up"]
    assert not (live / "backups").exists()


def test_a_dev_backup_goes_beside_the_dev_database_and_never_into_the_live_folder(
    run: RunCli, live: Path, dev: Path, checkout: Path, clock: list[datetime]
) -> None:
    connect(live / DATABASE_NAME).close()
    dev.mkdir(parents=True)
    connect(dev / DATABASE_NAME).close()

    exit_code, _, err = run(checkout, "backup", host=FakeHost())

    assert exit_code == 0, err
    assert daily(dev, local_day(NOON)).is_file()
    assert not (live / "backups").exists()


def test_the_backup_copies_only_the_database(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    connect(live / DATABASE_NAME).close()
    (live / "screenshots").mkdir()
    (live / "screenshots" / "a.jpg").write_bytes(b"image")

    assert run(code, "backup", host=host)[0] == 0

    backups = live / "backups"
    assert [path.relative_to(backups) for path in backups.rglob("*")] == [
        Path("daily"),
        daily(live, local_day(NOON)).relative_to(backups),
    ]


def test_a_backup_that_fails_its_integrity_check_is_not_kept_and_the_older_ones_stay(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    damaged(live / DATABASE_NAME)
    yesterday = daily(live, local_day(NOON - timedelta(days=1)))
    yesterday.parent.mkdir(parents=True)
    yesterday.write_text("yesterday's backup\n")

    exit_code, _, err = run(code, "backup", host=host)

    assert exit_code == 1
    assert err.startswith(
        f"backup failed: the copy of {live / DATABASE_NAME} failed its integrity check: "
    )
    assert list(yesterday.parent.iterdir()) == [yesterday]


def set_aside(live: Path, moment: datetime) -> Path:
    stamp = moment.astimezone().strftime("%Y-%m-%dT%H%M%S")
    return live / "backups" / "set-aside" / f"history-{stamp}.db"


def backend_calls(host: FakeHost) -> list[str]:
    return [call for call, label in host.calls if label == BACKEND.label and call != "job"]


def test_restore_stops_the_backend_sets_the_database_aside_and_starts_it_again(
    run: RunCli,
    tmp_path: Path,
    live: Path,
    stable: tuple[Path, FakeHost],
    clock: list[datetime],
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "kept in the backup"):
        pass
    assert run(code, "backup", host=host)[0] == 0
    clock[0] = NOON + timedelta(days=1)
    left_with_a_wal(live / DATABASE_NAME, tmp_path, "kept in the backup", "after the backup")
    host.calls.clear()

    exit_code, out, err = run(code, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 0, err
    aside = set_aside(live, clock[0])
    assert backend_calls(host) == ["unload", "load"]
    assert host.jobs[BACKEND.label].pid is not None
    assert stored_ids(live / DATABASE_NAME) == ["kept in the backup"]
    assert stored_ids(aside) == ["after the backup", "kept in the backup"]
    assert out[1:] == [
        f"Restored the daily backup of {local_day(NOON).isoformat()} into {live / DATABASE_NAME}",
        f"  from          {daily(live, local_day(NOON))}",
        f"  set aside     {aside} (never deleted)",
        f"  backend       {BACKEND.label} stopped, then started again",
    ]


def test_restore_of_a_day_with_no_backup_changes_nothing(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "current"):
        pass
    assert run(code, "backup", host=host)[0] == 0
    host.calls.clear()

    exit_code, _, err = run(code, "restore", "2026-01-02", host=host)

    assert exit_code == 1
    assert err == (
        "restore failed: no daily backup of 2026-01-02; the kept ones are"
        f" {local_day(NOON).isoformat()} (nothing was changed)\n"
    )
    assert backend_calls(host) == []
    assert not (live / "backups" / "set-aside").exists()


def test_restore_refuses_while_another_process_still_has_the_database_open(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "current"):
        pass
    assert run(code, "backup", host=host)[0] == 0
    host.calls.clear()

    with writer(live / DATABASE_NAME, "a terminal's ingest --watch"):
        exit_code, _, err = run(code, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 1
    assert err.startswith("restore failed: another process has ")
    assert err.endswith(" (nothing was changed; the backend was started again)\n")
    assert backend_calls(host) == ["unload", "load"]
    assert stored_ids(live / DATABASE_NAME) == ["a terminal's ingest --watch", "current"]
    assert not (live / "backups" / "set-aside").exists()


def test_restore_of_a_damaged_backup_puts_the_database_back(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "current"):
        pass
    daily(live, local_day(NOON)).parent.mkdir(parents=True)
    damaged(daily(live, local_day(NOON)))
    host.calls.clear()

    exit_code, _, err = run(code, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 1
    assert "failed its integrity check" in err
    assert stored_ids(live / DATABASE_NAME) == ["current"]
    assert backend_calls(host) == ["unload", "load"]
    assert list((live / "backups" / "set-aside").iterdir()) == []


def test_restore_leaves_a_backend_that_was_not_running_stopped(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "current"):
        pass
    assert run(code, "backup", host=host)[0] == 0
    host.unload(BACKEND.label)
    host.calls.clear()

    exit_code, out, err = run(code, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 0, err
    assert backend_calls(host) == []
    assert out[-1] == f"  backend       {BACKEND.label} was not loaded; left stopped"


def test_a_dev_restore_never_touches_the_stable_backend(
    run: RunCli, live: Path, dev: Path, checkout: Path, clock: list[datetime]
) -> None:
    host = FakeHost(loaded=[BACKEND.label])
    dev.mkdir(parents=True)
    with writer(dev / DATABASE_NAME, "dev"):
        pass
    assert run(checkout, "backup", host=host)[0] == 0
    host.calls.clear()

    exit_code, out, err = run(checkout, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 0, err
    assert host.calls == []
    assert stored_ids(dev / DATABASE_NAME) == ["dev"]
    assert out[-1] == f"  set aside     {set_aside(dev, NOON)} (never deleted)"


def test_a_wrong_restore_is_undone_by_restoring_the_database_it_set_aside(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "old"):
        pass
    assert run(code, "backup", host=host)[0] == 0
    with writer(live / DATABASE_NAME, "new"):
        pass
    clock[0] = NOON + timedelta(minutes=1)
    assert run(code, "restore", local_day(NOON).isoformat(), host=host)[0] == 0
    clock[0] = NOON + timedelta(minutes=2)

    wrong = set_aside(live, NOON + timedelta(minutes=1))
    exit_code, out, err = run(code, "restore", str(wrong), host=host)

    assert exit_code == 0, err
    assert stored_ids(live / DATABASE_NAME) == ["new", "old"]
    assert stored_ids(set_aside(live, clock[0])) == ["old"]
    assert out[1] == f"Restored {wrong} into {live / DATABASE_NAME}"


def test_install_adds_a_daily_backup_launch_agent_and_uninstall_removes_it(
    run: RunCli, live: Path, checkout: Path
) -> None:
    host = FakeHost(checks={COMMIT: gate_runs()})
    layout = stable_layout()

    code, out, err = run(checkout, "install", host=host)

    assert code == 0, err
    plist = plistlib.loads((layout.launch_agents / f"{DAILY_BACKUP.label}.plist").read_bytes())
    assert plist["ProgramArguments"] == [str(layout.command(layout.current)), "backup"]
    assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 0}
    assert plist["RunAtLoad"] is True
    assert "KeepAlive" not in plist
    assert DAILY_BACKUP.label in host.jobs
    assert (
        f"  LaunchAgent   {DAILY_BACKUP.label} loaded: computer-history backup, daily at 03:00"
        " and at login" in out
    )

    assert run(checkout, "uninstall", host=host)[0] == 0

    assert DAILY_BACKUP.label not in host.jobs
    assert not (layout.launch_agents / f"{DAILY_BACKUP.label}.plist").exists()


BACKUPS_SECTION = "Backups:"
STATUS = ("status", "--aw-url", "http://127.0.0.1:1/api/0")


def section(out: list[str], title: str) -> list[str]:
    start = out.index(title) + 1
    end = next((i for i in range(start, len(out)) if not out[i].startswith("  ")), len(out))
    return out[start:end]


def taken_at(path: Path, moment: datetime) -> None:
    os.utime(path, (moment.timestamp(), moment.timestamp()))


def test_a_pre_update_backup_is_kept_apart_from_the_dailies_and_never_pruned_with_them(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "before the update"):
        pass

    taken = take_pre_update_backup(live / DATABASE_NAME, version="bbbbbbb", now=NOON)
    for n in range(DAILY_KEPT + 2):
        clock[0] = NOON + timedelta(days=n)
        assert run(code, "backup", host=host)[0] == 0

    stamp = NOON.astimezone().strftime("%Y-%m-%dT%H%M%S")
    assert taken.target == live / "backups" / "pre-update" / f"history-{stamp}-bbbbbbb.db"
    assert stored_ids(taken.target) == ["before the update"]
    assert len(list(daily(live, NOON.date()).parent.iterdir())) == DAILY_KEPT


def test_status_shows_the_latest_backup_how_many_are_kept_and_their_integrity(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    connect(live / DATABASE_NAME).close()
    before_update = NOON - timedelta(days=5)
    taken = take_pre_update_backup(live / DATABASE_NAME, version="bbbbbbb", now=before_update)
    taken_at(taken.target, before_update)
    for n in (2, 1, 0):
        clock[0] = NOON - timedelta(days=n)
        assert run(code, "backup", host=host)[0] == 0
        taken_at(daily(live, local_day(clock[0])), clock[0])
    clock[0] = NOON + timedelta(hours=2)

    _, out, _ = run(code, *STATUS, host=host)

    latest = daily(live, local_day(NOON))
    size = human_size(latest.stat().st_size)
    assert section(out, BACKUPS_SECTION) == [
        f"  latest        {local_day(NOON).isoformat()}, taken {when(NOON)} (2h ago), {size}",
        f"  daily         3 kept (the newest {DAILY_KEPT}), oldest"
        f" {local_day(NOON - timedelta(days=2)).isoformat()}",
        f"  pre-update    1 kept, newest taken {when(before_update)}",
        "  integrity     each passed SQLite's integrity check before it was kept",
        f"  folder        {live / 'backups'}",
    ]


def test_status_warns_when_the_daily_backup_has_not_run_since_before_yesterday(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    connect(live / DATABASE_NAME).close()
    assert run(code, "backup", host=host)[0] == 0
    clock[0] = NOON + timedelta(days=2)

    _, out, _ = run(code, *STATUS, host=host)

    assert section(out, BACKUPS_SECTION)[-1] == (
        f"  warning: no daily backup since {local_day(NOON).isoformat()}; check that"
        f" {DAILY_BACKUP.label} is loaded and read its log"
    )


def test_status_before_any_backup_says_where_they_will_go(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable

    _, out, _ = run(code, *STATUS, host=host)

    assert section(out, BACKUPS_SECTION) == [
        f"  none yet (the daily backup takes one a day into {live / 'backups' / 'daily'})"
    ]
