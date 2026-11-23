"""How update swaps in a changed capture agent, checks it records, and puts the old one back."""

from __future__ import annotations

import os
import signal
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cli_output import STATUS, RunCli, section
from fake_aw import FakeAW
from fake_host import (
    AgentStart,
    FakeHost,
    agent_built_from,
    completes_a_cycle,
    crashes,
    fails_to_register,
    gate_runs,
    lay_out_agent,
    records,
    stays_silent,
    write_record,
)
from stable_updates import (
    NEWER,
    NEWEST,
    OLDER,
    OLDEST,
    health,
    install_older,
    log_lines,
    stable_code,
    updating,
)

from computer_history.cli import formatting as cli_formatting
from computer_history.cli import update as cli_update
from computer_history.sources import CAPTURE_KIND, PAUSED_KIND, SPOOL_ENV_VAR, default_spool_path
from computer_history.stable import (
    AGENT_ACTIVE_SECONDS,
    AGENT_WAIT_SECONDS,
    BACKEND,
    Layout,
    installed_agent,
    record_installed_agent,
    version_name,
)
from computer_history.stable.updates import waiting
from computer_history.store import load_migrations

START = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
AFK_BUCKET = "aw-watcher-afk_test-host.local"
AGENT_FELL_BACK_EXIT_CODE = 3
NEW, OLD = version_name(NEWER), version_name(OLDER)
SILENT = (
    f"the new capture agent recorded nothing in {AGENT_ACTIVE_SECONDS:g}s while you were active"
)


class Clock:
    """The update's wall clock and monotonic clock, moved on only by its sleeps."""

    def __init__(self, *, interrupt_on_sleep: int | None = None) -> None:
        self.at = START
        self.elapsed = 0.0
        self.sleeps = 0
        self.interrupt_on_sleep = interrupt_on_sleep

    def now(self) -> datetime:
        return self.at

    def monotonic(self) -> float:
        return self.elapsed

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        if self.sleeps == self.interrupt_on_sleep:
            os.kill(os.getpid(), signal.SIGTERM)
        self.at += timedelta(seconds=seconds)
        self.elapsed += seconds


@pytest.fixture(autouse=True)
def quick_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(waiting, "FIRST_CYCLE_POLL_SECONDS", 0.001)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(cli_formatting, "utc_now", clock.now)
    monkeypatch.setattr(cli_update, "time", clock)
    return clock


@pytest.fixture
def aw(monkeypatch: pytest.MonkeyPatch) -> FakeAW:
    """An ActivityWatch whose aw-afk shows the user active from the start for an hour."""
    aw = FakeAW({AFK_BUCKET: "afkstatus"}, t0=START)
    monkeypatch.setattr(cli_update, "AWClient", lambda *args, **kwargs: aw)
    return aw


def active(aw: FakeAW, from_minute: float = 0) -> None:
    if from_minute > 0:
        aw.add(AFK_BUCKET, 0, from_minute * 60, {"status": "afk"})
    aw.add(AFK_BUCKET, from_minute, 3600, {"status": "not-afk"})


@pytest.fixture
def layout(run: RunCli, live: Path, checkout: Path) -> Layout:
    layout = install_older(run, live, checkout)
    lay_out_agent(layout.capture_agent_app, OLDER)
    record_installed_agent(layout, OLDER, START - timedelta(days=1))
    return layout


def spool(layout: Layout) -> Path:
    return default_spool_path(layout.database)


def agent_update(layout: Layout, *starts: AgentStart, **options: object) -> FakeHost:
    """main with NEWER passing, its backend completing a cycle and its agent's source changed."""
    return updating(
        layout,
        completes_a_cycle(health(layout)),
        agent_trees={NEWER: "f" * 40, NEWEST: "f" * 40},
        agent_starts=starts,
        **options,
    )


def agent_line(out: list[str]) -> str:
    (line,) = [line for line in out if line.startswith("  agent ")]
    return line


def installs(host: FakeHost) -> list[str]:
    return [label for call, label in host.calls if call == "install_agent"]


def test_an_installed_agent_record_nested_past_the_parser_limit_reads_as_unknown(
    layout: Layout,
) -> None:
    layout.installed_agent.write_text("[" * 100_000)

    assert installed_agent(layout) is None


def test_a_record_from_the_new_agent_verifies_it_and_the_update_line_says_so(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    host = agent_update(layout, records(spool(layout), clock.now))

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == "  agent         updated and verified: the new capture agent records"
    assert agent_built_from(layout.capture_agent_app) == NEWER
    found = installed_agent(layout)
    assert found is not None and found.built_from == NEWER
    assert installs(host) == [str(layout.agent_app(layout.versions / NEW))]
    assert host.notifications == []
    (entry,) = log_lines(layout)
    assert entry["action"] == "updated"
    assert entry["agent"] == "updated and verified"
    assert clock.sleeps == 0


def test_the_first_agent_update_keeps_the_installed_app_in_the_old_version_to_fall_back_to(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    old_folder = layout.versions / OLD
    assert not layout.agent_app(old_folder).exists()

    code, _, err = run(
        stable_code(layout), "update", host=agent_update(layout, records(spool(layout), clock.now))
    )

    assert code == 0, err
    assert agent_built_from(layout.agent_app(old_folder)) == OLDER
    assert layout.agent_commit(old_folder).read_text() == f"{OLDER}\n"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")
def test_a_failed_copy_of_the_installed_app_leaves_it_running_and_the_old_copy_as_it_was(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    old_folder = layout.versions / OLD
    lay_out_agent(layout.agent_app(old_folder), OLDEST)
    layout.agent_commit(old_folder).write_text(f"{OLDEST}\n")
    unreadable = layout.capture_agent_app / "Contents" / "Resources" / "locked"
    unreadable.parent.mkdir(parents=True)
    unreadable.write_text("x")
    unreadable.chmod(0)

    host = agent_update(layout, stays_silent)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == f"  agent         not swapped: {OLD}'s capture agent keeps running"
    (warning,) = [line for line in out if "warning" in line]
    assert warning.startswith(
        f"  warning: the installed capture agent could not be kept in {OLD}: "
    )
    assert installs(host) == []
    assert host.notifications == []
    (updated,) = log_lines(layout)
    assert (updated["action"], updated["agent"]) == ("updated", "not swapped")
    found = installed_agent(layout)
    assert found is not None and found.built_from == OLDER
    assert agent_built_from(layout.agent_app(old_folder)) == OLDEST
    assert not (layout.agent_app(old_folder) / "Contents" / "Resources").exists()
    assert layout.agent_commit(old_folder).read_text() == f"{OLDEST}\n"
    assert sorted(path.name for path in old_folder.iterdir() if "Agent" in path.name) == [
        layout.agent_app(old_folder).name
    ]
    assert agent_built_from(layout.capture_agent_app) == OLDER


def test_an_installed_agent_that_cannot_be_unregistered_is_left_running_and_not_swapped(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    host = agent_update(layout, agent_unregister_errors=["Operation not permitted"])

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == f"  agent         not swapped: {OLD}'s capture agent keeps running"
    assert [line for line in out if "warning" in line] == [
        "  warning: the installed capture agent could not be unregistered, so it keeps running:"
        " Operation not permitted"
    ]
    assert agent_built_from(layout.capture_agent_app) == OLDER
    found = installed_agent(layout)
    assert found is not None and found.built_from == OLDER
    assert host.notifications == []


def test_a_new_agent_that_cannot_be_unregistered_at_fallback_is_said_to_stay(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    host = agent_update(
        layout, stays_silent, agent_unregister_errors=[None, "Operation not permitted"]
    )

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == AGENT_FELL_BACK_EXIT_CODE, err
    assert [line for line in out if "warning" in line] == [
        "  warning: the new capture agent could not be unregistered, so it stays: Operation not"
        " permitted (run capture-agent/scripts/install.sh from a checkout at main)"
    ]
    assert agent_built_from(layout.capture_agent_app) == NEWER


def test_the_wait_ends_the_moment_a_record_arrives(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    host = agent_update(layout, stays_silent)
    later = records(spool(layout), clock.now)
    sleep = clock.sleep

    def sleep_then_record(seconds: float) -> None:
        sleep(seconds)
        if clock.sleeps == 3:
            later(host)

    clock.sleep = sleep_then_record  # type: ignore[method-assign]

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out).startswith("  agent         updated and verified")
    assert clock.sleeps == 3


def test_paused_capture_skips_the_wait_and_says_not_verified(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    write_record(spool(layout), PAUSED_KIND, START - timedelta(seconds=1))
    host = agent_update(layout, stays_silent)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == "  agent         installed, not verified: capture is paused"
    assert agent_built_from(layout.capture_agent_app) == NEWER
    assert log_lines(layout)[-1]["agent"] == "installed, not verified"
    assert clock.sleeps == 0


def test_a_paused_record_from_the_new_agent_verifies_it(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    host = agent_update(layout, records(spool(layout), clock.now, PAUSED_KIND))

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == "  agent         updated and verified: the new capture agent records"
    assert clock.sleeps == 0


def test_a_record_written_while_launchd_is_still_checking_the_agent_verifies_it(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    first = records(spool(layout), clock.now)

    def records_then_launchd_checks(host: FakeHost) -> None:
        first(host)
        clock.at += timedelta(seconds=5)

    host = agent_update(layout, records_then_launchd_checks)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == "  agent         updated and verified: the new capture agent records"
    found = installed_agent(layout)
    assert found is not None and found.installed_at == START


def test_the_check_reads_the_stable_spool_whatever_the_shell_sets(
    run: RunCli,
    layout: Layout,
    clock: Clock,
    aw: FakeAW,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active(aw)
    monkeypatch.setenv(SPOOL_ENV_VAR, str(tmp_path / "elsewhere"))
    host = agent_update(layout, records(spool(layout), clock.now))

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == "  agent         updated and verified: the new capture agent records"


def test_no_afk_bucket_ends_the_wait_at_once_installed_not_verified(
    run: RunCli, layout: Layout, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    aw = FakeAW({"aw-watcher-window_test-host.local": "currentwindow"}, t0=START)
    monkeypatch.setattr(cli_update, "AWClient", lambda *args, **kwargs: aw)
    host = agent_update(layout, stays_silent)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == (
        "  agent         installed, not verified: ActivityWatch could not say whether you were"
        " active"
    )
    assert clock.sleeps == 0


def test_a_database_that_fails_to_read_mid_wait_ends_installed_not_verified(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)

    def breaks_the_database(_: FakeHost) -> None:
        with closing(sqlite3.connect(layout.database)) as conn:
            conn.execute("DROP TABLE observations")

    host = agent_update(layout, breaks_the_database)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out).startswith(
        "  agent         installed, not verified: your activity since the swap could not be read: "
    )
    assert agent_built_from(layout.capture_agent_app) == NEWER
    assert log_lines(layout)[-1]["agent"] == "installed, not verified"


def test_a_silent_agent_after_a_schema_migration_is_not_verified_rather_than_put_back(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)

    def migrates(_: FakeHost) -> None:
        with closing(sqlite3.connect(layout.database)) as conn:
            conn.execute(f"PRAGMA user_version = {len(load_migrations()) + 1}")

    host = agent_update(layout, migrates)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == (
        f"  agent         installed, not verified: the new capture agent recorded nothing in"
        f" {AGENT_ACTIVE_SECONDS:g}s while you were active, but the database's schema is newer"
        " than this update reads, so only the spool was checked"
    )
    assert agent_built_from(layout.capture_agent_app) == NEWER
    assert host.notifications == []


def test_an_unreachable_activitywatch_ends_the_wait_installed_not_verified(
    run: RunCli, layout: Layout, clock: Clock
) -> None:
    host = agent_update(layout, stays_silent)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == (
        "  agent         installed, not verified: ActivityWatch could not say whether you were"
        " active"
    )
    assert agent_built_from(layout.capture_agent_app) == NEWER
    assert host.notifications == []


def test_never_active_within_the_wait_ends_installed_not_verified(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    aw.add(AFK_BUCKET, 0, 3600, {"status": "afk"})
    host = agent_update(layout, stays_silent)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == (
        "  agent         installed, not verified: you were not active for"
        f" {AGENT_ACTIVE_SECONDS:g}s within the {AGENT_WAIT_SECONDS:g}s wait"
    )
    assert agent_built_from(layout.capture_agent_app) == NEWER
    assert AGENT_WAIT_SECONDS <= clock.elapsed < AGENT_WAIT_SECONDS + 5


def test_a_silent_agent_while_active_falls_back_to_the_old_app_and_keeps_the_new_backend(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    write_record(spool(layout), CAPTURE_KIND, START - timedelta(seconds=1))
    host = agent_update(layout, stays_silent)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == AGENT_FELL_BACK_EXIT_CODE, err
    assert f"Updated to version {NEW} (commit {NEWER}) from {OLD}" in out
    assert agent_line(out) == f"  agent         fell back to {OLD}'s capture agent: {SILENT}"
    new_folder = layout.versions / NEW
    kept = layout.fell_back_agent_app(new_folder)
    assert f"  kept          {kept} (the build that fell back)" in out
    assert not [line for line in out if "warning" in line]
    assert layout.current.resolve() == new_folder
    assert agent_built_from(layout.capture_agent_app) == OLDER
    assert agent_built_from(kept) == NEWER
    assert layout.fell_back_agent_commit(new_folder).read_text() == f"{NEWER}\n"
    assert agent_built_from(layout.agent_app(new_folder)) == OLDER
    assert layout.agent_commit(new_folder).read_text() == f"{OLDER}\n"
    found = installed_agent(layout)
    assert found is not None and found.built_from == OLDER
    assert installs(host) == [
        str(layout.agent_app(layout.versions / NEW)),
        str(layout.agent_app(layout.versions / OLD)),
    ]
    assert host.notifications == [
        f"The capture agent from {NEW} fell back to {OLD}'s: {SILENT}. Its build is kept at {kept}."
    ]
    fell_back, updated = log_lines(layout)
    assert {k: fell_back[k] for k in ("action", "from", "to", "reason")} == {
        "action": "agent fell back",
        "from": NEW,
        "to": OLD,
        "reason": SILENT,
    }
    assert (updated["action"], updated["agent"]) == ("updated", "fell back")
    assert AGENT_ACTIVE_SECONDS <= clock.elapsed < AGENT_ACTIVE_SECONDS + 5


def test_idle_time_does_not_count_toward_the_wait(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw, from_minute=5)
    host = agent_update(layout, stays_silent)

    code, _, err = run(stable_code(layout), "update", host=host)

    assert code == AGENT_FELL_BACK_EXIT_CODE, err
    assert 300 + AGENT_ACTIVE_SECONDS <= clock.elapsed < 300 + AGENT_ACTIVE_SECONDS + 5


def test_an_agent_that_cannot_be_registered_is_put_back_at_once(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    host = agent_update(layout, fails_to_register("launchd never showed it running"))

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == AGENT_FELL_BACK_EXIT_CODE, err
    assert agent_line(out) == (
        f"  agent         fell back to {OLD}'s capture agent: the new capture agent could not be"
        " started: launchd never showed it running"
    )
    assert agent_built_from(layout.capture_agent_app) == OLDER
    assert clock.sleeps == 0


def test_an_interrupt_during_the_wait_falls_back_and_exits_130(
    run: RunCli, layout: Layout, monkeypatch: pytest.MonkeyPatch, aw: FakeAW
) -> None:
    active(aw)
    clock = Clock(interrupt_on_sleep=2)
    monkeypatch.setattr(cli_formatting, "utc_now", clock.now)
    monkeypatch.setattr(cli_update, "time", clock)

    def interrupted_again(_: object) -> None:
        os.kill(os.getpid(), signal.SIGINT)

    host = agent_update(layout, stays_silent, interrupted_again)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 130, err
    reason = "the update was interrupted while waiting for the new capture agent's first record"
    assert agent_line(out) == f"  agent         fell back to {OLD}'s capture agent: {reason}"
    assert agent_built_from(layout.capture_agent_app) == OLDER
    assert log_lines(layout)[0]["reason"] == reason
    assert layout.current.resolve() == layout.versions / NEW


def test_a_failing_fallback_step_is_reported_and_the_rest_still_run(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    host = agent_update(
        layout,
        stays_silent,
        fails_to_register("launchd never showed it running"),
        notify_error="notifications are off",
    )

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == AGENT_FELL_BACK_EXIT_CODE, err
    assert agent_line(out) == f"  agent         fell back to {OLD}'s capture agent: {SILENT}"
    assert [line for line in out if "warning" in line] == [
        f"  warning: {OLD}'s capture agent could not be put back: launchd never showed it"
        " running (run capture-agent/scripts/install.sh from a checkout at main)",
        "  warning: the notification could not be posted: notifications are off",
    ]
    assert installed_agent(layout) is None
    fell_back, updated = log_lines(layout)
    assert fell_back["action"] == "agent fell back"
    assert updated["agent"] == "fell back"


def test_the_next_update_retries_an_agent_that_fell_back_though_its_source_is_unchanged(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    first = agent_update(layout, stays_silent)
    assert run(stable_code(layout), "update", host=first)[0] == AGENT_FELL_BACK_EXIT_CODE
    assert agent_built_from(layout.capture_agent_app) == OLDER
    host = FakeHost(
        checks={NEWEST: gate_runs(), NEWER: gate_runs(), OLDER: gate_runs()},
        loaded=[BACKEND.label],
        backend_starts=[completes_a_cycle(health(layout))],
        agent_trees={NEWER: "f" * 40, NEWEST: "f" * 40},
        agent_starts=[records(spool(layout), clock.now)],
    )

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert ("build_agent", NEWEST) in host.calls
    assert agent_line(out).startswith("  agent         updated and verified")
    assert agent_built_from(layout.capture_agent_app) == NEWEST
    assert agent_built_from(layout.fell_back_agent_app(layout.versions / NEW)) == NEWER
    _, out, _ = run(stable_code(layout), *STATUS, host=host)
    install = section(out, "Stable install:")
    assert install[3].startswith(f"  agent         built from {version_name(NEWEST)}, installed ")
    assert install[4].startswith(f"  last update   updated {NEW} -> {version_name(NEWEST)}, ")


def test_an_unchanged_agent_is_not_installed_and_the_update_line_says_so(
    run: RunCli, layout: Layout, clock: Clock
) -> None:
    host = updating(layout, completes_a_cycle(health(layout)), agent_trees={NEWER: "e" * 40})
    host.agent_trees[OLDER] = "e" * 40

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_line(out) == "  agent         unchanged (its source is the same)"
    assert installs(host) == []
    assert log_lines(layout)[-1]["agent"] == "unchanged"


def test_a_backend_fallback_never_installs_the_agent(
    run: RunCli, layout: Layout, clock: Clock
) -> None:
    host = updating(layout, crashes, agent_trees={NEWER: "f" * 40})

    code, out, _ = run(stable_code(layout), "update", host=host)

    assert code == 1
    assert installs(host) == []
    assert agent_built_from(layout.capture_agent_app) == OLDER
    assert not [line for line in out if line.startswith("  agent ")]


def test_status_shows_the_agents_build_and_its_last_fallback(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    host = agent_update(layout, stays_silent)
    assert run(stable_code(layout), "update", host=host)[0] == AGENT_FELL_BACK_EXIT_CODE

    _, out, _ = run(stable_code(layout), *STATUS, host=host)

    install = section(out, "Stable install:")
    assert install[1].startswith(f"  current       {NEW}, installed ")
    assert install[3].startswith(f"  agent         built from {OLD}, installed ")
    assert install[4].startswith(f"                fell back {NEW} -> {OLD}, ")
    assert install[4].endswith(f" ago): {SILENT}")
    assert install[5].startswith(f"  last update   updated {OLD} -> {NEW}, ")


def test_status_shows_no_fallback_for_an_agent_that_never_fell_back(
    run: RunCli, layout: Layout, clock: Clock, aw: FakeAW
) -> None:
    active(aw)
    host = agent_update(layout, records(spool(layout), clock.now))
    assert run(stable_code(layout), "update", host=host)[0] == 0

    _, out, _ = run(stable_code(layout), *STATUS, host=host)

    install = section(out, "Stable install:")
    assert install[3].startswith(f"  agent         built from {NEW}, installed ")
    assert install[4].startswith(f"  last update   updated {OLD} -> {NEW}, ")
