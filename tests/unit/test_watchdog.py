"""The watchdog through the CLI, with the fake host adapter and a fake ActivityWatch."""

from __future__ import annotations

import json
import plistlib
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from cli_output import RunCli, section
from fake_aw import T0, FakeAW
from fake_host import FakeHost, gate_runs, installed_package

from computer_history.cli import status as cli_status
from computer_history.cli import watchdog as cli_watchdog
from computer_history.host import OPEN_ACTIVITYWATCH
from computer_history.sources import (
    CAPTURE_KIND,
    PAUSED_KIND,
    SPOOL_VERSION,
    AWError,
    write_backend_heartbeat,
)
from computer_history.stable import ACTIVITYWATCH_AT_LOGIN, WATCHDOG, stable_layout
from computer_history.watchdog import NOTIFICATION_TITLE, REOPEN_LIMIT

COMMIT = "b" * 40
HOST = "test-host.local"
AFK_BUCKET = f"aw-watcher-afk_{HOST}"
WINDOW_BUCKET = f"aw-watcher-window_{HOST}"
CAPTURE_SILENT = "The capture agent has recorded nothing for over 5 min while you were active."
CAPTURE_BACK = "The capture agent is recording again."
AW_DOWN = "ActivityWatch has been unreachable for over 5 min."
AW_BACK = "ActivityWatch is recording again."
BACKEND_SILENT = "The backend has finished no ingest cycle for over 5 min while you were active."


class UnreachableAW(FakeAW):
    def get_buckets(self) -> dict[str, dict[str, object]]:
        raise AWError("ActivityWatch unreachable at http://127.0.0.1:5600/api/0: refused")


class Mac:
    """A Mac on a minute clock: ActivityWatch's watchers, the capture agent's spool and the
    backend's heartbeat, each kept going or stopped by the test."""

    def __init__(self, folder: Path, run: RunCli, checkout: Path, host: FakeHost) -> None:
        self.db = folder / "history.db"
        self.spool = folder / "spool"
        self.spool.mkdir(parents=True, exist_ok=True)
        self.run_cli, self.checkout, self.host = run, checkout, host
        self.aw = FakeAW({AFK_BUCKET: "afkstatus", WINDOW_BUCKET: "currentwindow"})
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
                write_backend_heartbeat(self.db.parent / "backend-heartbeat.json", self.now, True)
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
        content = kind == CAPTURE_KIND
        line = {
            "version": SPOOL_VERSION,
            "id": f"00000000-0000-4000-8000-{self.records:012x}",
            "captured_at": self.now.strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{self.now.microsecond // 1000:03d}Z",
            "kind": kind,
            "trigger": "heartbeat" if content else None,
            "app_name": "Editor" if content else None,
            "bundle_id": None,
            "window_title": "w" if content else None,
            "text": "t" if content else None,
            "text_sha256": "0" * 64 if content else None,
            "full_text_bytes": 1 if content else None,
            "text_cut_off": False if content else None,
            "timed_out": False if content else None,
        }
        with (self.spool / "open.part").open("a", encoding="utf-8") as spool:
            spool.write(json.dumps(line) + "\n")

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
        return [message for _, message in self.host.notifications]

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
    monkeypatch.setattr(cli_watchdog, "utc_now", lambda: mac.now)
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

    assert mac.host.notifications[0][0] == NOTIFICATION_TITLE
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
        f"ActivityWatch has recorded nothing for over 5 min in {WINDOW_BUCKET}."
    ]


def test_thresholds_come_from_the_config_file(mac: Mac) -> None:
    config = {"watchdog": {"capture_agent_minutes": 10, "backend_minutes": "soon"}}
    (mac.db.parent / "agent-config.json").write_text(json.dumps(config))

    mac.run(minutes(0, 2))
    mac.run(minutes(3, 20), record=None, cycle=False)

    assert mac.notified_at(BACKEND_SILENT) == [8]
    capture = "The capture agent has recorded nothing for over 10 min while you were active."
    assert mac.notified_at(capture) == [13]
    assert (
        "config problem: watchdog.backend_minutes must be a number of minutes from 1 to 1440,"
        " using 5"
    ) in mac.errors[-1]
    assert mac.outputs[-1][1].startswith("Watchdog (silent after: capture agent 10m,")


def test_a_notification_that_fails_to_post_is_tried_again_next_run(mac: Mac) -> None:
    mac.run(minutes(0, 2))
    mac.host.notify_error = "could not post a notification: osascript failed"
    mac.run(minutes(3, 8), record=None)
    assert mac.notified == []
    assert "error: could not post a notification: osascript failed" in mac.errors[-1]

    mac.host.notify_error = None
    mac.run([9], record=None)

    assert mac.notified == [CAPTURE_SILENT]


def test_status_shows_the_stable_watchdogs_findings(
    monkeypatch: pytest.MonkeyPatch, run: RunCli, live: Path, checkout: Path
) -> None:
    host = FakeHost(checks={COMMIT: gate_runs()})
    assert run(checkout, "install", host=host)[0] == 0
    stable = installed_package(stable_layout().link.resolve().parents[1])
    _, out, _ = run(checkout, "status", "--aw-url", "http://127.0.0.1:1/api/0", host=host)
    assert section(out, "Stable watchdog:") == [
        f"  last run       none yet (no state at {live / 'watchdog.json'})"
    ]

    mac = on_the_clock(monkeypatch, Mac(live, run, stable, host))
    mac.run(minutes(0, 2))
    mac.run(minutes(3, 8), record=None)
    monkeypatch.setattr(cli_status, "utc_now", lambda: mac.now + timedelta(seconds=30))
    _, out, _ = run(checkout, "status", "--aw-url", "http://127.0.0.1:1/api/0", host=host)

    shown = section(out, "Stable watchdog:")
    assert shown[0].startswith("  last run       ") and shown[0].endswith(" (30s ago)")
    assert shown[1].startswith("  capture agent  PROBLEM: silent while you were active")
    assert shown[1].endswith(" (6m 30s ago), notified 30s ago")
    assert shown[2].startswith("  ActivityWatch  ok: recording")
    assert shown[3].startswith("  backend        ok: recording")
    assert shown[4:] == []

    monkeypatch.setattr(cli_status, "utc_now", lambda: mac.now + timedelta(minutes=10))
    _, out, _ = run(checkout, "status", "--aw-url", "http://127.0.0.1:1/api/0", host=host)

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
