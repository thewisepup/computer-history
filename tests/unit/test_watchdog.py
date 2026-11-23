"""The watchdog through the CLI, with the fake host adapter and a fake ActivityWatch."""

from __future__ import annotations

import fcntl
import json
import plistlib
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from cli_output import STATUS, UNREACHABLE_AW, RunCli, section
from fake_aw import T0, FakeAW, UnreachableAW
from fake_host import FakeHost, gate_runs, installed_package
from spool_records import spool_line

from computer_history.cli import formatting as cli_formatting
from computer_history.cli import watchdog as cli_watchdog
from computer_history.host import OPEN_ACTIVITYWATCH
from computer_history.sources import (
    CAPTURE_KIND,
    PAUSED_KIND,
    WINDOW_SOURCE,
    AWError,
    IngestHealth,
    agent_config_path,
    agent_health,
    health_path,
    write_health,
)
from computer_history.stable import ACTIVITYWATCH_AT_LOGIN, WATCHDOG, stable_layout
from computer_history.store import DATABASE_NAME
from computer_history.watchdog import (
    REOPEN_LIMIT,
    WatchdogState,
    read_state_or_fresh,
    read_thresholds,
    watchdog_lock_path,
    watchdog_state_path,
)

COMMIT = "b" * 40
HOST = "test-host.local"
AFK_BUCKET = f"aw-watcher-afk_{HOST}"
WINDOW_BUCKET = f"aw-watcher-window_{HOST}"
CAPTURE_SILENT = "The capture agent has recorded nothing for over 5 min while you were active."
CAPTURE_BACK = "The capture agent is recording again."
AW_DOWN = "ActivityWatch has been unreachable for over 5 min."
AW_BACK = "ActivityWatch is recording again."
BACKEND_SILENT = "The backend has finished no ingest cycle for over 5 min while you were active."


class WatchedAW(FakeAW):
    """The fake ActivityWatch, where a bucket listed as missing answers its events with a 404."""

    def __init__(self, buckets: dict[str, str]) -> None:
        super().__init__(buckets)
        self.missing: set[str] = set()

    def get_events(self, bucket_id: str, **query: object) -> list[dict[str, object]]:
        if bucket_id in self.missing:
            raise AWError(f"ActivityWatch answered 404 for {bucket_id}")
        return super().get_events(bucket_id, **query)  # type: ignore[arg-type]


class Mac:
    """A Mac on a minute clock: ActivityWatch's watchers, the capture agent's spool and the
    backend's ingest cycles, each kept going or stopped by the test."""

    def __init__(self, folder: Path, run: RunCli, checkout: Path, host: FakeHost) -> None:
        self.db = folder / DATABASE_NAME
        self.spool = folder / "spool"
        self.spool.mkdir(parents=True, exist_ok=True)
        self.run_cli, self.checkout, self.host = run, checkout, host
        self.aw = WatchedAW({AFK_BUCKET: "afkstatus", WINDOW_BUCKET: "currentwindow"})
        self.reachable = True
        self.minute = 0.0
        self.records = 0
        self.outputs: list[list[str]] = []
        self.ran_at: list[float] = []
        self.errors: list[str] = []

    @property
    def now(self) -> datetime:
        return T0 + timedelta(minutes=self.minute)

    def client(self) -> FakeAW:
        return self.aw if self.reachable else UnreachableAW({})

    def run(
        self,
        minutes: Iterable[float],
        *,
        active: bool = True,
        record: str | None = CAPTURE_KIND,
        cycle: bool = True,
        failing: str | None = None,
        afk_watcher: bool = True,
        window_watcher: bool = True,
    ) -> None:
        """Each minute the watchers, agent and backend do as told, then the watchdog runs."""
        for minute in minutes:
            start, self.minute = self.minute, minute
            status = "not-afk" if active else "afk"
            seconds = (minute - start) * 60
            if afk_watcher:
                self.watched(AFK_BUCKET, start, seconds, {"status": status})
            if window_watcher:
                self.watched(WINDOW_BUCKET, start, seconds, {"app": "Editor", "title": "w"})
            if record is not None:
                self.record(record)
            if cycle:
                health = IngestHealth(self.now, last_success_at=self.now)
                if failing is not None:
                    health = IngestHealth(self.now, 1, self.now, last_error=failing)
                write_health(health_path(self.db), health)
            self.watch()

    def watched(self, bucket: str, start: float, seconds: float, data: dict[str, str]) -> None:
        """A watcher's heartbeats: the newest event grows while its data stays the same."""
        events = self.aw.events[bucket]
        last = events[-1] if events else None
        if last is not None and last["data"] == data:
            last_end = datetime.fromisoformat(last["timestamp"]) + timedelta(
                seconds=last["duration"]
            )
            if last_end == T0 + timedelta(minutes=start):
                last["duration"] += seconds
                return
        self.aw.add(bucket, start, seconds, data)

    def record(self, kind: str) -> None:
        self.records += 1
        with (self.spool / "open.part").open("a", encoding="utf-8") as spool:
            spool.write(spool_line(self.records, self.now, kind) + "\n")

    def watch(self) -> list[str]:
        code, out, err = self.run_cli(
            self.checkout, "watchdog", "--db-path", str(self.db), host=self.host
        )
        assert code == 0, err
        self.outputs.append(out)
        self.ran_at.append(self.minute)
        self.errors.append(err)
        return out

    @property
    def notified(self) -> list[str]:
        return list(self.host.notifications)

    def notified_at(self, message: str) -> list[float]:
        """The minutes whose watchdog run printed a line containing the message."""
        return [
            minute
            for minute, out in zip(self.ran_at, self.outputs, strict=True)
            if any(message in line for line in out)
        ]


def on_the_clock(monkeypatch: pytest.MonkeyPatch, mac: Mac) -> Mac:
    """Point the watchdog command at the Mac's ActivityWatch, host name and clock."""
    monkeypatch.setattr(cli_watchdog, "AWClient", lambda *args, **kwargs: mac.client())
    monkeypatch.setattr(cli_watchdog, "gethostname", lambda: HOST)
    monkeypatch.setattr(cli_formatting, "utc_now", lambda: mac.now)
    return mac


@pytest.fixture
def mac(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run: RunCli, checkout: Path) -> Mac:
    return on_the_clock(monkeypatch, Mac(tmp_path / "data", run, checkout, FakeHost()))


def minutes(first: int, last: int) -> range:
    return range(first, last + 1)


def test_install_adds_the_watchdog_and_activitywatch_login_agents_and_uninstall_removes_them(
    run: RunCli, live: Path, checkout: Path
) -> None:
    host = FakeHost(checks={COMMIT: gate_runs()})
    layout = stable_layout()

    code, out, err = run(checkout, "install", host=host)

    assert code == 0, err
    watchdog = plistlib.loads(WATCHDOG.plist(layout).read_bytes())
    assert watchdog["ProgramArguments"] == [str(layout.command(layout.current)), "watchdog"]
    assert watchdog["StartInterval"] == 60
    assert watchdog["RunAtLoad"] is True
    assert "KeepAlive" not in watchdog
    opener = plistlib.loads(ACTIVITYWATCH_AT_LOGIN.plist(layout).read_bytes())
    assert opener["ProgramArguments"] == list(OPEN_ACTIVITYWATCH)
    assert opener["RunAtLoad"] is True
    assert "KeepAlive" not in opener and "StartInterval" not in opener
    assert {WATCHDOG.label, ACTIVITYWATCH_AT_LOGIN.label} <= set(host.jobs)
    assert f"  LaunchAgent   {WATCHDOG.label} loaded: computer-history watchdog, every 60s" in out
    opens = " ".join(OPEN_ACTIVITYWATCH)
    assert f"  LaunchAgent   {ACTIVITYWATCH_AT_LOGIN.label} loaded: {opens}, once at login" in out

    code, out, err = run(checkout, "uninstall", host=host)

    assert code == 0, err
    assert host.jobs == {}
    assert not WATCHDOG.plist(layout).exists()
    assert not ACTIVITYWATCH_AT_LOGIN.plist(layout).exists()


def test_all_recording_notifies_nothing(mac: Mac) -> None:
    mac.run(minutes(0, 30))

    assert mac.host.notifications == []
    findings = mac.outputs[-1][2:]
    assert [line.split(", last seen ")[0] for line in findings] == [
        "  capture agent  ok: recording",
        "  ActivityWatch  ok: recording",
        "  backend        ok: recording",
    ]
    assert all(line.endswith(" (0s ago)") for line in findings)


def test_a_silent_capture_agent_while_active_notifies_once_an_hour_then_once_when_it_clears(
    mac: Mac,
) -> None:
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 69), record=None)
    mac.run(minutes(70, 75))

    assert mac.notified == [CAPTURE_SILENT, CAPTURE_SILENT, CAPTURE_BACK]
    assert mac.notified_at(f"notified: {CAPTURE_SILENT}") == [8, 68]
    assert mac.notified_at(f"cleared: {CAPTURE_BACK}") == [70]
    assert mac.outputs[8][2].startswith("  capture agent  PROBLEM: silent while you were active")


@pytest.mark.parametrize("quiet", ["idle", "paused"])
def test_silence_while_idle_or_paused_never_notifies(mac: Mac, quiet: str) -> None:
    mac.run(minutes(0, 2))
    if quiet == "paused":
        mac.run([3], record=PAUSED_KIND)
    mac.run(minutes(4, 40), record=None, active=quiet == "paused", cycle=quiet == "paused")

    assert mac.host.notifications == []
    reason = "paused" if quiet == "paused" else "silent, but aw-afk does not show you active"
    assert mac.outputs[-1][2].startswith(f"  capture agent  cannot tell: {reason}")


def test_after_a_sleep_silence_counts_from_the_first_run_after_wake(mac: Mac) -> None:
    mac.run(minutes(0, 10))
    mac.minute = 100
    mac.run(minutes(101, 105), record=None)
    assert mac.host.notifications == []
    assert mac.outputs[-1][2].startswith(
        "  capture agent  cannot tell: silent, but watched only since the watchdog resumed"
    )

    mac.run(minutes(106, 107), record=None)

    assert mac.notified == [CAPTURE_SILENT]


def test_a_silent_backend_while_active_notifies(mac: Mac) -> None:
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 10), cycle=False)

    assert mac.notified == [BACKEND_SILENT]
    assert mac.notified_at(BACKEND_SILENT) == [8]


def test_an_activitywatch_outage_notifies_even_while_idle_and_reopens_it_three_times_an_hour(
    mac: Mac,
) -> None:
    mac.host.running_activitywatch = False
    mac.host.opening_starts_activitywatch = False
    mac.run(minutes(0, 1), active=False)
    mac.reachable = False
    mac.run(minutes(2, 70), active=False, record=None, cycle=False)

    assert mac.notified == [AW_DOWN, AW_DOWN]
    assert mac.notified_at(AW_DOWN) == [7, 67]
    reopened = mac.notified_at("  reopened ActivityWatch")
    assert reopened == [2, 3, 4, 62, 63, 64]
    refused = f"  did not reopen ActivityWatch: reopened {REOPEN_LIMIT} times in the last hour"
    assert mac.notified_at(refused) == [*minutes(5, 61), *minutes(65, 70)]


def test_activitywatch_reopened_within_the_threshold_never_notifies(mac: Mac) -> None:
    mac.host.running_activitywatch = False
    mac.run(minutes(0, 2))
    mac.reachable = False
    mac.run([3], cycle=False)
    mac.reachable = True
    mac.run(minutes(4, 20))

    assert mac.host.calls.count(("open_activitywatch", "")) == 1
    assert mac.host.notifications == []


def test_activitywatch_back_after_an_outage_notifies_the_clear(mac: Mac) -> None:
    mac.host.running_activitywatch = False
    mac.host.opening_starts_activitywatch = False
    mac.run(minutes(0, 2))
    mac.reachable = False
    mac.run(minutes(3, 9), cycle=False)
    mac.reachable = True
    mac.run(minutes(10, 12))

    assert mac.notified == [AW_DOWN, AW_BACK]


def test_a_watcher_bucket_not_advancing_notifies_and_names_it(mac: Mac) -> None:
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 10), window_watcher=False)

    assert mac.notified == [
        f"ActivityWatch has recorded nothing for over 5 min in {WINDOW_SOURCE}."
    ]


def test_thresholds_come_from_the_config_file(mac: Mac) -> None:
    config = {"watchdog": {"capture_agent_minutes": 10, "backend_minutes": "soon"}}
    agent_config_path(mac.db).write_text(json.dumps(config))

    mac.run(minutes(0, 2))
    mac.run(minutes(3, 20), record=None, cycle=False)

    assert mac.notified_at(BACKEND_SILENT) == [8]
    capture = "The capture agent has recorded nothing for over 10 min while you were active."
    assert mac.notified_at(capture) == [13]
    problem = (
        "config problem: watchdog.backend_minutes must be a number of minutes from 1 to 1440,"
        " using 5"
    )
    assert [problem in err for err in mac.errors] == [True] + [False] * 20
    assert f"  {problem}" in mac.outputs[-1]
    assert mac.outputs[-1][1].startswith("Watchdog (silent after: capture agent 10m,")


def test_a_config_or_state_nested_past_the_parser_limit_is_unreadable_not_a_crash(
    tmp_path: Path,
) -> None:
    config, state = tmp_path / "agent-config.json", tmp_path / "watchdog.json"
    config.write_text("[" * 100_000)
    state.write_text("[" * 100_000)

    thresholds = read_thresholds(config)
    fresh, problem = read_state_or_fresh(state)

    assert thresholds.silent_after == read_thresholds(tmp_path / "missing.json").silent_after
    [found] = thresholds.problems
    assert found.startswith(f"cannot read {config}: ") and found.endswith("using the defaults")
    assert fresh == WatchdogState() and problem is not None


def test_a_notification_that_fails_to_post_is_tried_again_next_run(mac: Mac) -> None:
    mac.run(minutes(0, 2))
    mac.host.notify_error = "could not post a notification: osascript failed"
    mac.run(minutes(3, 8), record=None)
    assert mac.notified == []
    failed = "error: could not post a notification: osascript failed"
    assert [failed in err for err in mac.errors] == [False] * 8 + [True]

    mac.host.notify_error = None
    mac.run([9], record=None)

    assert mac.notified == [CAPTURE_SILENT]


def test_status_shows_the_stable_watchdogs_findings(
    monkeypatch: pytest.MonkeyPatch, run: RunCli, live: Path, checkout: Path
) -> None:
    host = FakeHost(checks={COMMIT: gate_runs()})
    assert run(checkout, "install", host=host)[0] == 0
    stable = installed_package(stable_layout().link.resolve().parents[1])
    _, out, _ = run(checkout, *STATUS, host=host)
    assert section(out, "Stable watchdog:") == [
        f"  last run       none yet (no state at {watchdog_state_path(live / DATABASE_NAME)})"
    ]

    mac = on_the_clock(monkeypatch, Mac(live, run, stable, host))
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 8), record=None)
    monkeypatch.setattr(cli_formatting, "utc_now", lambda: mac.now + timedelta(seconds=30))
    _, out, _ = run(checkout, *STATUS, host=host)

    shown = section(out, "Stable watchdog:")
    assert shown[0].startswith("  last run       ") and shown[0].endswith(" (30s ago)")
    assert shown[1].startswith("  capture agent  PROBLEM: silent while you were active")
    assert shown[1].endswith(" (6m 30s ago), notified 30s ago")
    assert shown[2].startswith("  ActivityWatch  ok: recording")
    assert shown[3].startswith("  backend        ok: recording")
    assert shown[4:] == []

    monkeypatch.setattr(cli_formatting, "utc_now", lambda: mac.now + timedelta(minutes=10))
    _, out, _ = run(checkout, *STATUS, host=host)

    assert section(out, "Stable watchdog:")[-1] == (
        "  warning: the watchdog last ran 10m ago; it runs every minute while its LaunchAgent"
        " is loaded"
    )


def test_a_notified_problem_that_turns_to_cannot_tell_is_not_cleared(mac: Mac) -> None:
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 8), record=None)
    mac.run(minutes(9, 20), record=None, active=False)
    assert mac.notified == [CAPTURE_SILENT]

    mac.run([21])

    assert mac.notified == [CAPTURE_SILENT, CAPTURE_BACK]


def test_a_bucket_answering_404_has_no_end_and_never_makes_activitywatch_unreachable(
    mac: Mac,
) -> None:
    gone = f"aw-watcher-window-gone_{HOST}"
    mac.aw.create_bucket(gone, "currentwindow", T0)
    mac.aw.missing.add(gone)

    mac.run(minutes(0, 10))

    assert mac.host.notifications == []
    assert mac.outputs[-1][3].startswith("  ActivityWatch  ok: recording")

    mac.aw.missing.add(WINDOW_BUCKET)
    mac.run(minutes(11, 20))

    assert mac.notified == [
        f"ActivityWatch has recorded nothing for over 5 min in {WINDOW_SOURCE}."
    ]
    assert mac.outputs[-1][3].startswith("  ActivityWatch  PROBLEM: not advancing")


def test_an_old_or_empty_bucket_beside_a_live_one_is_no_problem(mac: Mac) -> None:
    old = f"aw-watcher-window-old_{HOST}"
    mac.aw.create_bucket(old, "currentwindow", T0 - timedelta(days=30))
    mac.aw.add(old, -30 * 24 * 60, 60, {"app": "Editor", "title": "w"})
    mac.aw.create_bucket(f"aw-watcher-afk-empty_{HOST}", "afkstatus", T0)

    mac.run(minutes(0, 20))

    assert mac.host.notifications == []


def test_failing_cycles_are_left_to_ingests_own_alert_and_never_notify_from_the_watchdog(
    mac: Mac,
) -> None:
    reason = "aw-window: ActivityWatch answered 500"
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 30), failing=reason)

    assert mac.notified == []
    assert mac.outputs[-1][4].startswith(
        "  backend        ok: running, but its cycles fail (ingest alerts on that)"
    )
    assert mac.outputs[-1][4].endswith(f" ({reason})")


def test_a_failed_cycle_clears_a_silent_backend_since_it_is_running_again(mac: Mac) -> None:
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 8), cycle=False)
    assert mac.notified == [BACKEND_SILENT]

    mac.run([9], failing="database is locked")

    assert mac.notified == [BACKEND_SILENT, "The backend is finishing ingest cycles again."]


def test_a_database_read_error_cannot_tell_and_keeps_the_silence_counting(
    monkeypatch: pytest.MonkeyPatch, mac: Mac
) -> None:
    ingest = ("ingest", "--db-path", str(mac.db), *UNREACHABLE_AW)
    code, _, _ = mac.run_cli(mac.checkout, *ingest)
    assert code in (0, 1)
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 5), record=None)

    def broken(*_: object, **__: object) -> object:
        raise sqlite3.DatabaseError("database disk image is malformed")

    with monkeypatch.context() as broken_store:
        broken_store.setattr(agent_health, "stored_afk_spans", broken)
        mac.run(minutes(6, 7), record=None)
    assert mac.host.notifications == []
    assert mac.outputs[-1][2] == (
        "  capture agent  cannot tell: cannot be read"
        " (database read failed: database disk image is malformed)"
    )
    assert mac.outputs[-1][4].startswith("  backend        ok: recording")

    mac.run([8], record=None)

    assert mac.notified == [CAPTURE_SILENT]


def test_a_second_outage_after_a_clear_gets_its_own_notification(mac: Mac) -> None:
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 8), record=None)
    mac.run(minutes(9, 10))
    mac.run(minutes(11, 17), record=None)

    assert mac.notified == [CAPTURE_SILENT, CAPTURE_BACK, CAPTURE_SILENT]
    assert mac.notified_at(f"notified: {CAPTURE_SILENT}") == [8, 16]


def test_a_run_that_cannot_take_the_lock_exits_quietly(mac: Mac) -> None:
    mac.run(minutes(0, 2))
    saved = watchdog_state_path(mac.db).read_bytes()

    with watchdog_lock_path(mac.db).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        mac.minute = 3
        out = mac.watch()

    assert out[1:] == [] and mac.errors[-1] == ""
    assert watchdog_state_path(mac.db).read_bytes() == saved
    assert mac.watch()[1].startswith("Watchdog")


def test_a_repeated_error_is_logged_once_an_hour_but_shown_every_run(mac: Mac) -> None:
    mac.host.notify_error = "could not post a notification: osascript failed"
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 70), record=None)

    failed = f"error: {mac.host.notify_error}"
    logged = [minute for minute, err in zip(mac.ran_at, mac.errors, strict=True) if failed in err]
    assert logged == [8, 68]
    assert mac.notified_at(f"  {failed}") == list(minutes(8, 70))


def test_a_repair_install_leaves_the_loaded_activitywatch_agent_alone(
    run: RunCli, live: Path, checkout: Path
) -> None:
    host = FakeHost(checks={COMMIT: gate_runs()})
    assert run(checkout, "install", host=host)[0] == 0
    host.calls.clear()

    assert run(checkout, "install", host=host)[0] == 0

    assert ("unload", ACTIVITYWATCH_AT_LOGIN.label) not in host.calls
    assert ("unload", WATCHDOG.label) in host.calls

    ACTIVITYWATCH_AT_LOGIN.plist(stable_layout()).write_bytes(plistlib.dumps({"Label": "old"}))
    assert run(checkout, "install", host=host)[0] == 0

    assert ("unload", ACTIVITYWATCH_AT_LOGIN.label) in host.calls
