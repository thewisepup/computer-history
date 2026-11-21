from __future__ import annotations

import os
import plistlib
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from cli_output import STATUS, RunCli, section
from db_states import damaged, left_with_a_wal, stored_ids, writer
from fake_host import FakeHost, gate_runs, installed_package

from computer_history.cli import formatting as cli_formatting
from computer_history.cli.formatting import human_size, when
from computer_history.sources import WINDOW_SOURCE
from computer_history.stable import (
    BACKEND,
    BACKUPS_FOLDER_NAME,
    DAILY_BACKUP,
    DAILY_FOLDER_NAME,
    DAILY_KEPT,
    PRE_UPDATE_FOLDER_NAME,
    SET_ASIDE_FOLDER_NAME,
    TAKEN_AT_STAMP,
    WATCHDOG,
    daily_backup_path,
    stable_layout,
    take_pre_update_backup,
    version_name,
)
from computer_history.stable import launch_agents as stable_launch_agents
from computer_history.stable.launch_agents import LaunchAgent
from computer_history.store import DATABASE_NAME, connect, sidecars, supported_version

COMMIT = "b" * 40
NOON = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
BACKUPS = "Backups:"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """The time the commands see; set its one item to move it."""
    now = [NOON]
    monkeypatch.setattr(cli_formatting, "utc_now", lambda: now[0])
    return now


@pytest.fixture
def stable(run: RunCli, live: Path, checkout: Path) -> tuple[Path, FakeHost]:
    host = FakeHost(checks={COMMIT: gate_runs()})
    assert run(checkout, "install", host=host)[0] == 0
    return installed_package(stable_layout().link.resolve().parents[1]), host


def local_day(moment: datetime) -> date:
    return moment.astimezone().date()


def daily(folder: Path, moment: datetime) -> Path:
    return daily_backup_path(folder / DATABASE_NAME, local_day(moment))


def set_aside(folder: Path, moment: datetime) -> Path:
    stamp = moment.astimezone().strftime(TAKEN_AT_STAMP)
    return folder / BACKUPS_FOLDER_NAME / SET_ASIDE_FOLDER_NAME / f"history-{stamp}.db"


def names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def agent_calls(host: FakeHost, agent: LaunchAgent) -> list[str]:
    return [call for call, label in host.calls if label == agent.label and call != "job"]


def taken_at(path: Path, moment: datetime) -> None:
    os.utime(path, (moment.timestamp(), moment.timestamp()))


def backed_up(run: RunCli, code: Path, host: FakeHost, live: Path, *source_ids: str) -> None:
    with writer(live / DATABASE_NAME, *source_ids):
        pass
    assert run(code, "backup", host=host)[0] == 0


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
    copy = daily(live, NOON)
    assert out[0] == (
        f"Profile stable (version {version_name(COMMIT)}), database {live / DATABASE_NAME}"
    )
    assert out[1] == f"Backed up {live / DATABASE_NAME}"
    assert out[2] == f"  copied to {copy}"
    assert out[3].startswith(f"  schema v{supported_version()}, ")
    assert out[3].endswith(", integrity ok")
    assert stored_ids(copy) == ["a", "b"]


def test_the_daily_backup_keeps_the_newest_seven_days_with_none_of_the_older_files(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    connect(live / DATABASE_NAME).close()
    moments = [NOON - timedelta(days=n) for n in range(9, 0, -1)]
    for moment in moments:
        daily(live, moment).parent.mkdir(parents=True, exist_ok=True)
        daily(live, moment).write_text("an older backup\n")
    for sidecar in sidecars(daily(live, moments[0])):
        sidecar.write_text("left by a reader\n")
    stray = daily(live, moments[0]).with_name("notes.txt")
    stray.write_text("mine\n")

    exit_code, out, err = run(code, "backup", host=host)

    assert exit_code == 0, err
    kept = [daily(live, moment).name for moment in [*moments[-6:], NOON]]
    assert names(stray.parent) == sorted([*kept, stray.name])
    assert out[4:] == [f"  removed   {daily(live, moment)}" for moment in moments[:3]]


def test_a_second_run_on_the_same_day_keeps_the_days_first_backup(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    backed_up(run, code, host, live, "morning")
    with writer(live / DATABASE_NAME, "evening"):
        pass
    clock[0] = NOON + timedelta(hours=3)

    exit_code, out, err = run(code, "backup", host=host)

    assert exit_code == 0, err
    assert out[1:] == [f"Today's backup is already taken: {daily(live, NOON)}"]
    assert stored_ids(daily(live, NOON)) == ["morning"]


@pytest.mark.parametrize("leftover", ["a WAL file alone", "an empty database file"])
def test_a_leftover_in_place_of_todays_backup_is_cleared_and_the_backup_taken(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime], leftover: str
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "today"):
        pass
    target = daily(live, NOON)
    target.parent.mkdir(parents=True)
    (sidecars(target)[0] if leftover == "a WAL file alone" else target).write_bytes(b"")

    exit_code, out, err = run(code, "backup", host=host)

    assert exit_code == 0, err
    assert out[1] == f"Backed up {live / DATABASE_NAME}"
    assert names(target.parent) == [target.name]
    assert stored_ids(target) == ["today"]


def test_a_day_missed_with_the_lid_closed_is_taken_when_the_backup_next_runs(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    backed_up(run, code, host, live)
    clock[0] = NOON + timedelta(days=2, hours=7)

    exit_code, _, err = run(code, "backup", host=host)

    assert exit_code == 0, err
    assert names(daily(live, NOON).parent) == [daily(live, NOON).name, daily(live, clock[0]).name]


def test_a_backup_with_no_database_yet_takes_nothing_and_succeeds(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable

    exit_code, out, err = run(code, "backup", host=host)

    assert exit_code == 0, err
    assert out[1:] == [f"No database at {live / DATABASE_NAME} yet: nothing to back up"]
    assert not (live / BACKUPS_FOLDER_NAME).exists()


def test_a_dev_backup_goes_beside_the_dev_database_and_never_into_the_live_folder(
    run: RunCli, live: Path, dev: Path, checkout: Path, clock: list[datetime]
) -> None:
    connect(live / DATABASE_NAME).close()
    dev.mkdir(parents=True)
    connect(dev / DATABASE_NAME).close()

    exit_code, _, err = run(checkout, "backup", host=FakeHost())

    assert exit_code == 0, err
    assert daily(dev, NOON).is_file()
    assert not (live / BACKUPS_FOLDER_NAME).exists()


def test_the_backup_is_only_the_database_and_reading_it_leaves_no_journal_files(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    connect(live / DATABASE_NAME).close()
    (live / "screenshots").mkdir()
    (live / "screenshots" / "a.jpg").write_bytes(b"image")

    assert run(code, "backup", host=host)[0] == 0
    reader = sqlite3.connect(f"{daily(live, NOON).as_uri()}?mode=ro", uri=True)
    reader.execute("SELECT count(*) FROM sqlite_schema").fetchone()
    reader.close()

    backups = live / BACKUPS_FOLDER_NAME
    assert [path.relative_to(backups) for path in backups.rglob("*")] == [
        Path(DAILY_FOLDER_NAME),
        daily(live, NOON).relative_to(backups),
    ]


@pytest.mark.parametrize("damage", ["failed integrity check", "not a database"])
def test_a_failed_backup_exits_1_keeps_nothing_and_leaves_the_older_ones(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime], damage: str
) -> None:
    code, host = stable
    if damage == "not a database":
        (live / DATABASE_NAME).write_text("real history\n")
    else:
        damaged(live / DATABASE_NAME)
    yesterday = daily(live, NOON - timedelta(days=1))
    yesterday.parent.mkdir(parents=True)
    yesterday.write_text("yesterday's backup\n")

    exit_code, _, err = run(code, "backup", host=host)

    assert exit_code == 1
    assert err.startswith("backup failed: ")
    assert ("failed its integrity check" in err) == (damage == "failed integrity check")
    assert names(yesterday.parent) == [yesterday.name]


def test_restore_stops_the_agents_sets_the_database_aside_and_starts_them_again(
    run: RunCli,
    tmp_path: Path,
    live: Path,
    stable: tuple[Path, FakeHost],
    clock: list[datetime],
) -> None:
    code, host = stable
    backed_up(run, code, host, live, "kept in the backup")
    clock[0] = NOON + timedelta(days=1)
    left_with_a_wal(live / DATABASE_NAME, tmp_path, "kept in the backup", "after the backup")
    host.calls.clear()

    exit_code, out, err = run(code, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 0, err
    aside = set_aside(live, clock[0])
    assert agent_calls(host, BACKEND) == ["unload", "load"]
    assert agent_calls(host, DAILY_BACKUP) == ["unload", "load"]
    assert agent_calls(host, WATCHDOG) == ["unload", "load"]
    assert host.calls.index(("unload", DAILY_BACKUP.label)) < host.calls.index(
        ("unload", BACKEND.label)
    )
    assert stored_ids(live / DATABASE_NAME) == ["kept in the backup"]
    assert stored_ids(aside) == ["after the backup", "kept in the backup"]
    assert names(aside.parent) == [aside.name]
    assert names(daily(live, NOON).parent) == [daily(live, NOON).name]
    assert out[1:] == [
        f"Restored the daily backup of {local_day(NOON).isoformat()} into {live / DATABASE_NAME}",
        f"  from          {daily(live, NOON)}",
        f"  set aside     {aside} (never deleted)",
        f"  backend       {BACKEND.label} stopped, then started again",
        f"  watchdog      {WATCHDOG.label} stopped, then started again",
        f"  backup        {DAILY_BACKUP.label} stopped, then started again",
    ]


def test_restore_of_a_day_with_no_backup_changes_nothing(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    backed_up(run, code, host, live, "current")
    host.calls.clear()

    exit_code, _, err = run(code, "restore", "2026-01-02", host=host)

    assert exit_code == 1
    assert err == (
        "restore failed: no daily backup of 2026-01-02; the kept ones are"
        f" {local_day(NOON).isoformat()} (nothing was changed)\n"
    )
    assert [call for call, _ in host.calls if call != "job"] == []
    assert not (live / BACKUPS_FOLDER_NAME / SET_ASIDE_FOLDER_NAME).exists()


def test_restore_reads_only_a_dashed_day_as_a_day(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    backed_up(run, code, host, live, "current")
    host.calls.clear()

    exit_code, _, err = run(code, "restore", local_day(NOON).strftime("%Y%m%d"), host=host)

    assert exit_code == 1
    assert err == (
        f"restore failed: no backup at {local_day(NOON).strftime('%Y%m%d')} (nothing was changed)\n"
    )
    assert [call for call, _ in host.calls if call != "job"] == []
    with pytest.raises(SystemExit):
        run(code, "restore", "2026-13-01", host=host)


def test_restore_refuses_while_another_process_still_has_the_database_open(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    backed_up(run, code, host, live, "current")
    host.calls.clear()

    with writer(live / DATABASE_NAME, "a terminal's ingest --watch"):
        exit_code, _, err = run(code, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 1
    assert err.startswith("restore failed: another process has ")
    assert err.endswith(" (nothing was changed; backend, watchdog and backup started again)\n")
    assert agent_calls(host, BACKEND) == ["unload", "load"]
    assert host.jobs[BACKEND.label].pid is not None
    assert stored_ids(live / DATABASE_NAME) == ["a terminal's ingest --watch", "current"]
    assert not (live / BACKUPS_FOLDER_NAME / SET_ASIDE_FOLDER_NAME).exists()


def test_restore_holds_the_database_locked_while_it_moves_it_aside(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    live: Path,
    stable: tuple[Path, FakeHost],
    clock: list[datetime],
) -> None:
    code, host = stable
    backed_up(run, code, host, live, "kept in the backup")
    with writer(live / DATABASE_NAME, "current"):
        pass
    late: list[str] = []
    rename = Path.rename

    def opened_meanwhile(path: Path, target: Path) -> Path:
        if path == live / DATABASE_NAME:
            conn = sqlite3.connect(path, timeout=0)
            try:
                conn.execute("INSERT INTO observations VALUES (NULL, '', '', '', '', '', '')")
            except sqlite3.OperationalError as exc:
                late.append(str(exc))
            finally:
                conn.close()
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", opened_meanwhile)

    exit_code, _, err = run(code, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 0, err
    assert late == ["database is locked"]
    assert stored_ids(set_aside(live, NOON)) == ["current", "kept in the backup"]


def test_restore_starts_the_backend_again_when_it_will_not_stop(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    live: Path,
    stable: tuple[Path, FakeHost],
    clock: list[datetime],
) -> None:
    code, host = stable
    backed_up(run, code, host, live, "current")
    host.unload(DAILY_BACKUP.label)
    host.unload(WATCHDOG.label)
    monkeypatch.setattr(stable_launch_agents, "UNLOAD_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(stable_launch_agents, "LOAD_RETRY_SECONDS", 0)
    host.unload_lingers = 3
    host.calls.clear()

    exit_code, _, err = run(code, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 1
    assert err.startswith(f"restore failed: could not stop {BACKEND.label}: ")
    assert err.endswith(" (nothing was changed; backend started again)\n")
    assert agent_calls(host, BACKEND) == ["unload", "load", "load"]
    assert host.jobs[BACKEND.label].pid is not None
    assert stored_ids(live / DATABASE_NAME) == ["current"]
    assert not (live / BACKUPS_FOLDER_NAME / SET_ASIDE_FOLDER_NAME).exists()


def test_restore_of_a_damaged_backup_puts_the_database_back(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "current"):
        pass
    daily(live, NOON).parent.mkdir(parents=True)
    damaged(daily(live, NOON))
    host.calls.clear()

    exit_code, _, err = run(code, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 1
    assert "failed its integrity check" in err
    assert stored_ids(live / DATABASE_NAME) == ["current"]
    assert agent_calls(host, BACKEND) == ["unload", "load"]
    assert names(set_aside(live, NOON).parent) == []


def test_restore_leaves_a_backend_that_was_not_running_stopped(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    backed_up(run, code, host, live, "current")
    host.unload(BACKEND.label)
    host.calls.clear()

    exit_code, out, err = run(code, "restore", local_day(NOON).isoformat(), host=host)

    assert exit_code == 0, err
    assert agent_calls(host, BACKEND) == []
    assert out[-2:] == [
        f"  backup        {DAILY_BACKUP.label} stopped, then started again",
        f"  backend       {BACKEND.label} was not loaded; left stopped",
    ]


def test_restore_into_a_database_other_than_the_live_one_never_touches_launchd(
    run: RunCli, tmp_path: Path, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    other = tmp_path / "other"
    other.mkdir()
    with writer(other / DATABASE_NAME, "other"):
        pass
    assert run(code, "backup", "--db-path", str(other / DATABASE_NAME), host=host)[0] == 0
    host.calls.clear()

    restore = ("restore", "--db-path", str(other / DATABASE_NAME), local_day(NOON).isoformat())
    exit_code, out, err = run(code, *restore, host=host)

    assert exit_code == 0, err
    assert host.calls == []
    assert out[-1] == f"  set aside     {set_aside(other, NOON)} (never deleted)"


def test_restore_where_there_is_no_database_sets_nothing_aside(
    run: RunCli, tmp_path: Path, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    other = tmp_path / "other"
    other.mkdir()
    with writer(other / DATABASE_NAME, "other"):
        pass
    assert run(code, "backup", "--db-path", str(other / DATABASE_NAME), host=host)[0] == 0
    (other / DATABASE_NAME).unlink()

    restore = ("restore", "--db-path", str(other / DATABASE_NAME), local_day(NOON).isoformat())
    exit_code, out, err = run(code, *restore, host=host)

    assert exit_code == 0, err
    assert stored_ids(other / DATABASE_NAME) == ["other"]
    assert out[1:] == [
        f"Restored the daily backup of {local_day(NOON).isoformat()} into {other / DATABASE_NAME}",
        f"  from          {daily(other, NOON)}",
    ]


def test_a_dev_restore_never_touches_the_stable_agents(
    run: RunCli, live: Path, dev: Path, checkout: Path, clock: list[datetime]
) -> None:
    host = FakeHost(loaded=[BACKEND.label, DAILY_BACKUP.label])
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
    backed_up(run, code, host, live, "old")
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
    plist = plistlib.loads(DAILY_BACKUP.plist(layout).read_bytes())
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
    assert not DAILY_BACKUP.plist(layout).exists()


def test_a_pre_update_backup_is_kept_apart_from_the_dailies_and_never_pruned_with_them(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    with writer(live / DATABASE_NAME, "before the update"):
        pass

    version = version_name(COMMIT)
    taken = take_pre_update_backup(live / DATABASE_NAME, version=version, now=NOON)
    for n in range(DAILY_KEPT + 2):
        clock[0] = NOON + timedelta(days=n)
        assert run(code, "backup", host=host)[0] == 0

    stamp = NOON.astimezone().strftime(TAKEN_AT_STAMP)
    pre_update = live / BACKUPS_FOLDER_NAME / PRE_UPDATE_FOLDER_NAME
    assert taken.target == pre_update / f"history-{stamp}-{version}.db"
    assert stored_ids(taken.target) == ["before the update"]
    assert len(names(daily(live, NOON).parent)) == DAILY_KEPT


def test_status_shows_the_latest_backup_how_many_are_kept_and_their_integrity(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    connect(live / DATABASE_NAME).close()
    before_update = NOON - timedelta(days=5)
    version = version_name(COMMIT)
    taken = take_pre_update_backup(live / DATABASE_NAME, version=version, now=before_update)
    taken_at(taken.target, before_update)
    for n in (2, 1, 0):
        clock[0] = NOON - timedelta(days=n)
        assert run(code, "backup", host=host)[0] == 0
        taken_at(daily(live, clock[0]), clock[0])
    clock[0] = NOON + timedelta(hours=2)

    _, out, _ = run(code, *STATUS, host=host)

    size = human_size(daily(live, NOON).stat().st_size)
    assert section(out, BACKUPS) == [
        f"  latest        {local_day(NOON).isoformat()}, taken {when(NOON)} (2h ago), {size}",
        f"  daily         3 kept (the newest {DAILY_KEPT}), oldest"
        f" {local_day(NOON - timedelta(days=2)).isoformat()}",
        f"  pre-update    1 kept, newest taken {when(before_update)}",
        "  integrity     each passed SQLite's integrity check before it was kept",
        f"  folder        {live / BACKUPS_FOLDER_NAME}",
    ]


def test_status_warns_when_the_daily_backup_has_not_run_since_before_yesterday(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable
    backed_up(run, code, host, live)
    clock[0] = NOON + timedelta(days=2)

    _, out, _ = run(code, *STATUS, host=host)

    assert section(out, BACKUPS)[-1] == (
        f"  warning: no daily backup since {local_day(NOON).isoformat()}; check that"
        f" {DAILY_BACKUP.label} is loaded and read its log"
    )


def test_status_survives_a_backup_removed_while_it_lists_them(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    live: Path,
    stable: tuple[Path, FakeHost],
    clock: list[datetime],
) -> None:
    code, host = stable
    clock[0] = NOON - timedelta(days=1)
    backed_up(run, code, host, live)
    clock[0] = NOON
    assert run(code, "backup", host=host)[0] == 0
    listdir = os.listdir

    def removed_meanwhile(folder: str | os.PathLike[str]) -> list[str]:
        found = listdir(folder)
        daily(live, NOON - timedelta(days=1)).unlink(missing_ok=True)
        return found

    monkeypatch.setattr(os, "listdir", removed_meanwhile)

    exit_code, out, err = run(code, *STATUS, host=host)

    assert exit_code == 0, err
    assert f"  daily         1 kept (the newest {DAILY_KEPT}), oldest" in "\n".join(out)


def test_status_before_any_backup_says_where_they_will_go(
    run: RunCli, live: Path, stable: tuple[Path, FakeHost], clock: list[datetime]
) -> None:
    code, host = stable

    _, out, _ = run(code, *STATUS, host=host)

    assert section(out, BACKUPS) == [
        f"  none yet (the daily backup takes one a day into {daily(live, NOON).parent})"
    ]
