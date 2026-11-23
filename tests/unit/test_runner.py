from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from db_states import stored_progress
from fake_aw import FakeAW
from fake_source import FakeSource, at

from computer_history.sources import (
    POLL_INTERVAL_SECONDS,
    BackfillProgress,
    ChunkDone,
    CycleSummary,
    FailureKind,
    IngestOutcome,
    StreamFailure,
    plan_backfill,
    poll,
    run_backfill,
    watch,
)
from computer_history.sources.activitywatch import WINDOW_SOURCE, ActivityWatch
from computer_history.store import get_progress, table_counts

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
HOUR = timedelta(hours=1)


def stored(conn: sqlite3.Connection, stream: str) -> list[str]:
    rows = conn.execute(
        "SELECT source_id FROM observations WHERE source = ? ORDER BY started_at", (stream,)
    )
    return [row[0] for row in rows]


def window_aw(now: datetime) -> ActivityWatch:
    fake = FakeAW({WINDOW_BUCKET: "currentwindow"}, t0=now - timedelta(minutes=30))
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "Code"})
    return ActivityWatch(fake)


@pytest.fixture
def locker(db_path: Path, conn: sqlite3.Connection):
    conn.execute("PRAGMA busy_timeout = 50")
    other = sqlite3.connect(db_path, isolation_level=None)
    yield other
    if other.in_transaction:
        other.execute("ROLLBACK")
    other.close()


def test_poll_writes_each_stream_with_its_progress_and_resumes_after_it(
    conn: sqlite3.Connection,
) -> None:
    spool = FakeSource("ax-text", "ocr")
    spool.add("ax-text", "c1", 0)
    spool.add("ax-text", "c2", 1)
    spool.add("ocr", "o1", 0)
    summary = poll(conn, [spool], now=at(10))
    assert summary == CycleSummary(
        at(10),
        {"ax-text": IngestOutcome(2, 0, 0, at(2)), "ocr": IngestOutcome(1, 0, 0, at(1))},
    )
    progress = stored_progress(conn, "ax-text")
    assert progress.position == "ax-text.jsonl:2"

    spool.add("ax-text", "c3", 5)
    again = poll(conn, [spool], now=at(11))
    assert again.outcomes["ax-text"] == IngestOutcome(1, 0, 0, at(6))
    assert again.outcomes["ocr"] == IngestOutcome(0, 0, 0, None)
    progress = stored_progress(conn, "ocr")
    assert progress.advanced_at == at(10)
    assert stored(conn, "ax-text") == ["c1", "c2", "c3"]


def test_held_back_captures_wait_for_a_later_poll(conn: sqlite3.Connection) -> None:
    spool = FakeSource("ax-text")
    spool.add("ax-text", "c1", 0)
    spool.add("ax-text", "c2", 1)
    spool.unsettled.add("c2")
    assert poll(conn, [spool], now=at(5)).outcomes["ax-text"] == IngestOutcome(1, 0, 1, at(1))
    spool.unsettled.clear()
    assert poll(conn, [spool], now=at(6)).outcomes["ax-text"] == IngestOutcome(1, 0, 0, at(2))


def test_unavailable_source_mid_cycle_keeps_earlier_streams_and_other_sources(
    conn: sqlite3.Connection,
) -> None:
    now = datetime.now(UTC)
    spool = FakeSource("a", "b", "c")
    for stream in ("a", "b", "c"):
        spool.add(stream, f"{stream}1", 0)
    spool.down.add("b")
    summary = poll(conn, [spool, window_aw(now)], now=now)
    assert list(summary.outcomes) == ["a", WINDOW_SOURCE]
    assert summary.failures == (
        StreamFailure("b", "fake b spool is unreadable", FailureKind.SOURCE),
    )
    assert spool.pulled == ["a", "b"]
    assert stored(conn, "a") == ["a1"] and stored(conn, "c") == []
    assert len(stored(conn, WINDOW_SOURCE)) == 1


def test_source_that_cannot_list_its_streams_is_reported_without_a_stream(
    conn: sqlite3.Connection,
) -> None:
    spool = FakeSource("a")
    spool.listing_down = True
    summary = poll(conn, [spool], now=at(1))
    assert not summary.ok
    assert summary.failures == (
        StreamFailure(None, "fake source is not running", FailureKind.SOURCE),
    )


def test_busy_database_mid_cycle_keeps_earlier_streams_and_ends_the_cycle(
    conn: sqlite3.Connection, locker: sqlite3.Connection
) -> None:
    now = datetime.now(UTC)
    spool = FakeSource("a", "b")
    spool.add("a", "a1", 0)
    spool.add("b", "b1", 0)

    def lock_before_b(stream: str) -> None:
        if stream == "b" and not locker.in_transaction:
            locker.execute("BEGIN IMMEDIATE")

    spool.before_pull = lock_before_b
    aw = window_aw(now)
    summary = poll(conn, [spool, aw], now=now)
    assert list(summary.outcomes) == ["a"]
    assert summary.failures == (
        StreamFailure("b", "database is locked", FailureKind.DATABASE_BUSY),
    )
    assert stored(conn, "a") == ["a1"] and get_progress(conn, "b") is None
    assert stored(conn, WINDOW_SOURCE) == []

    locker.execute("ROLLBACK")
    spool.before_pull = None
    recovered = poll(conn, [spool, aw], now=now)
    assert recovered.ok and set(recovered.outcomes) == {"a", "b", WINDOW_SOURCE}
    assert table_counts(conn)["observations"] == 3


def test_an_unexpected_error_skips_its_source_and_the_other_sources_still_poll(
    conn: sqlite3.Connection,
) -> None:
    now = datetime.now(UTC)
    spool = FakeSource("a", "b")
    spool.add("a", "a1", 0)
    spool.add("b", "b1", 0)
    bug = KeyError("Q3 salaries.xlsx")

    def buggy(stream: str) -> None:
        raise bug

    spool.before_pull = buggy
    summary = poll(conn, [spool, window_aw(now)], now=now)

    assert summary.failures == (StreamFailure("a", "unexpected KeyError", FailureKind.UNEXPECTED),)
    assert summary.failures[0].exc is bug
    assert spool.pulled == ["a"]
    assert list(summary.outcomes) == [WINDOW_SOURCE]
    assert len(stored(conn, WINDOW_SOURCE)) == 1


def test_hard_database_errors_propagate(conn: sqlite3.Connection) -> None:
    spool = FakeSource("a")
    spool.add("a", "a1", 0)

    def corrupt(stream: str) -> None:
        raise sqlite3.DatabaseError("database disk image is malformed")

    spool.before_pull = corrupt
    with pytest.raises(sqlite3.DatabaseError, match="malformed"):
        poll(conn, [spool], now=at(1))


def test_watch_reports_every_cycle_and_sleeps_for_the_rest_of_the_interval(
    conn: sqlite3.Connection,
) -> None:
    spool = FakeSource("a")
    spool.add("a", "a1", 0)
    spool.listing_down = True
    nows = iter([at(0), at(2)])
    ticks = iter([0.0, 15.0, 100.0, 102.0])
    reports: list[tuple[CycleSummary, float]] = []
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        spool.listing_down = False
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        watch(
            conn,
            [spool],
            report=lambda summary, delay: reports.append((summary, delay)),
            interval=POLL_INTERVAL_SECONDS,
            clock=lambda: next(nows),
            monotonic=lambda: next(ticks),
            sleep=sleep,
        )
    assert sleeps == [POLL_INTERVAL_SECONDS - 15, POLL_INTERVAL_SECONDS - 2]
    (failed, first_delay), (succeeded, _) = reports
    assert not failed.ok and failed.at == at(0) and first_delay == sleeps[0]
    assert succeeded.ok and succeeded.at == at(2) and succeeded.outcomes["a"].inserted == 1


def test_watch_starts_the_next_cycle_at_once_after_a_slow_one(conn: sqlite3.Connection) -> None:
    ticks = iter([0.0, 90.0])
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        watch(
            conn,
            [],
            report=lambda *_: None,
            interval=60,
            monotonic=lambda: next(ticks),
            sleep=sleep,
        )
    assert sleeps == [0.0]


def test_poll_refuses_a_stream_fed_by_two_sources(conn: sqlite3.Connection) -> None:
    first, second = FakeSource("a"), FakeSource("b", "a")
    first.add("a", "a1", 0)
    with pytest.raises(ValueError, match="stream 'a' is fed by more than one source"):
        poll(conn, [first, second], now=at(5))
    assert second.pulled == []


def three_hours() -> FakeSource:
    spool = FakeSource("a")
    for capture_id, minute in [("a1", 10), ("a2", 70), ("held", 90), ("a3", 100), ("a4", 130)]:
        spool.add("a", capture_id, minute)
    spool.unsettled.add("held")
    return spool


def hourly_plan(spool: FakeSource, conn: sqlite3.Connection, **kwargs):
    return plan_backfill(
        spool, "a", progress=get_progress(conn, "a"), now=at(180), chunk=HOUR, **kwargs
    )


def test_backfill_reports_an_incomplete_chunk_once_and_sets_progress_from_it(
    conn: sqlite3.Connection,
) -> None:
    spool = three_hours()
    plan = hourly_plan(spool, conn)
    assert len(plan.chunks) == 3 and plan.covers_history
    chunks: list[ChunkDone] = []
    run = run_backfill(conn, spool, [plan], clock=lambda: at(180), on_chunk=chunks.append)
    assert run.ok
    (result,) = run.results
    assert [done.incomplete_from for done in chunks] == [None, at(90), None]
    assert result.incomplete == [(plan.chunks[1], at(90))]
    assert result.complete_until == at(90)
    assert result.progress is BackfillProgress.SET
    progress = stored_progress(conn, "a")
    assert progress.position == spool.positions[1] == f"range:{at(90).isoformat()}"
    assert progress.settled_until == at(90) and progress.advanced_at == at(180)
    assert stored(conn, "a") == ["a1", "a2", "a3", "a4"]


def test_backfill_stops_at_an_unavailable_source_and_keeps_committed_chunks(
    conn: sqlite3.Connection,
) -> None:
    spool = three_hours()
    plan = hourly_plan(spool, conn)

    def down_after_one(stream: str) -> None:
        if len(spool.pulled) == 2:
            spool.down.add(stream)

    spool.before_pull = down_after_one
    run = run_backfill(conn, spool, [plan], clock=lambda: at(180))
    assert run.failure == StreamFailure("a", "fake a spool is unreadable", FailureKind.SOURCE)
    (result,) = run.results
    assert result.chunks_done == 1 and result.progress is None
    assert stored(conn, "a") == ["a1"] and get_progress(conn, "a") is None


def test_backfill_stops_at_a_busy_database_before_progress_is_set(
    conn: sqlite3.Connection, locker: sqlite3.Connection
) -> None:
    spool = three_hours()

    def lock_before_last(stream: str) -> None:
        if len(spool.pulled) == 3:
            locker.execute("BEGIN IMMEDIATE")

    spool.before_pull = lock_before_last
    run = run_backfill(conn, spool, [hourly_plan(spool, conn)], clock=lambda: at(180))
    assert run.failure == StreamFailure("a", "database is locked", FailureKind.DATABASE_BUSY)
    assert run.results[0].chunks_done == 2
    assert get_progress(conn, "a") is None


def test_backfill_interrupted_reports_what_committed(conn: sqlite3.Connection) -> None:
    spool = three_hours()

    def interrupt_second(stream: str) -> None:
        if len(spool.pulled) == 2:
            raise KeyboardInterrupt

    spool.before_pull = interrupt_second
    run = run_backfill(conn, spool, [hourly_plan(spool, conn)], clock=lambda: at(180))
    assert run.interrupted and run.failure is None and not run.ok
    assert run.results[0].chunks_done == 1


def test_backfill_leaves_progress_alone_when_the_range_misses_history(
    conn: sqlite3.Connection,
) -> None:
    spool = three_hours()
    plan = hourly_plan(spool, conn, start=at(60))
    assert plan.earlier == (("a-spool", at(10)),) and not plan.covers_history
    (result,) = run_backfill(conn, spool, [plan], clock=lambda: at(180)).results
    assert result.progress is BackfillProgress.NOT_COVERED
    assert get_progress(conn, "a") is None


def test_backfill_reports_progress_set_meanwhile(conn: sqlite3.Connection) -> None:
    spool = three_hours()
    plan = hourly_plan(spool, conn)
    other = FakeSource("a")
    other.add("a", "elsewhere", 170)
    poll(conn, [other], now=at(175))
    (result,) = run_backfill(conn, spool, [plan], clock=lambda: at(180)).results
    assert result.progress is BackfillProgress.SET_MEANWHILE
    progress = stored_progress(conn, "a")
    assert progress.position == "a.jsonl:1"


def test_backfill_of_a_stream_with_progress_keeps_it(conn: sqlite3.Connection) -> None:
    spool = three_hours()
    poll(conn, [spool], now=at(180))
    before = stored_progress(conn, "a")
    plan = hourly_plan(spool, conn, start=at(0))
    assert plan.end == before.settled_until
    (result,) = run_backfill(conn, spool, [plan], clock=lambda: at(180)).results
    assert result.progress is BackfillProgress.KEPT
    assert get_progress(conn, "a") == before


def test_ctrl_c_while_reporting_a_finished_stream_is_reported_as_interrupted(
    conn: sqlite3.Connection,
) -> None:
    spool = three_hours()

    def interrupt(result) -> None:
        raise KeyboardInterrupt

    run = run_backfill(
        conn, spool, [hourly_plan(spool, conn)], clock=lambda: at(180), on_stream=interrupt
    )
    assert run.interrupted
    assert [result.chunks_done for result in run.results] == [3]


def test_held_back_events_without_a_settled_time_make_the_chunk_incomplete(
    conn: sqlite3.Connection,
) -> None:
    spool = three_hours()
    spool.range_reports_progress = False
    plan = hourly_plan(spool, conn)
    chunks: list[ChunkDone] = []
    (result,) = run_backfill(
        conn, spool, [plan], clock=lambda: at(180), on_chunk=chunks.append
    ).results
    second = plan.chunks[1]
    assert [done.incomplete_from for done in chunks] == [None, second.start, None]
    assert result.incomplete == [(second, second.start)]
    assert result.complete_until == second.start


def test_backfill_refuses_two_plans_for_one_stream(conn: sqlite3.Connection) -> None:
    spool = three_hours()
    plan = hourly_plan(spool, conn)
    with pytest.raises(ValueError, match="listed more than once"):
        run_backfill(conn, spool, [plan, plan], clock=lambda: at(180))
    assert spool.pulled == []
