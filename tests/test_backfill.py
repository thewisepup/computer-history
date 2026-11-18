"""Backfill: chunk planning, chunked ingest, cursor hand-off, and the CLI command.

All against FakeAW (no live ActivityWatch) and tmp-dir databases.
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fake_aw import FakeAW

from computer_history import cli
from computer_history.sources import (
    AFK_SOURCE,
    BACKFILL_CHUNK,
    CURSOR_OVERLAP_SECONDS,
    WINDOW_SOURCE,
    AWError,
    AWSource,
    discover_sources,
    ingest_source,
    plan_backfill,
    run_backfill,
)
from computer_history.sources import backfill as backfill_module
from computer_history.store import (
    connect,
    get_cursor,
    init_cursor,
    set_cursor,
    table_counts,
    to_utc,
)

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
AFK_BUCKET = "aw-watcher-afk_test-host.local"
WINDOW = AWSource(WINDOW_SOURCE, (WINDOW_BUCKET,))
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
DAYS = 20  # > 2 chunk widths of history
DAY = 1440  # minutes


def history_aw(now: datetime) -> FakeAW:
    """``DAYS`` days of history ending at ``now``; buckets created at its start.

    aw-window: a 10-minute event at 01:00 each day, plus the current window
    (started 5 minutes ago, still growing: held back).
    aw-afk: an hour of not-afk at 00:00 each day, plus the current state (held back).
    """
    fake = FakeAW(
        {WINDOW_BUCKET: "currentwindow", AFK_BUCKET: "afkstatus"},
        t0=now - timedelta(days=DAYS),
    )
    for day in range(DAYS):
        fake.add(WINDOW_BUCKET, day * DAY + 60, 600, {"app": "Code", "title": f"day {day}"})
        fake.add(AFK_BUCKET, day * DAY, 3600, {"status": "not-afk"})
    fake.add(WINDOW_BUCKET, DAYS * DAY - 5, 290, {"app": "Chrome", "title": "now"})
    fake.add(AFK_BUCKET, DAYS * DAY - 5, 290, {"status": "not-afk"})
    return fake


def stored(conn: sqlite3.Connection, source: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT source_id, started_at, ended_at FROM observations WHERE source = ?"
        " ORDER BY started_at",
        (source,),
    ).fetchall()


def window_plan(fake: FakeAW, conn: sqlite3.Connection, **kwargs: Any):
    return plan_backfill(fake, WINDOW, cursor=get_cursor(conn, WINDOW_SOURCE), now=NOW, **kwargs)


def backfill(conn: sqlite3.Connection, fake: FakeAW, plan):
    return run_backfill(conn, fake, plan, clock=lambda: NOW)


# --- planning ----------------------------------------------------------------------


def test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight(conn) -> None:
    fake = history_aw(NOW)
    created = to_utc(fake.buckets[WINDOW_BUCKET]["created"])
    plan = window_plan(fake, conn)

    local = plan.start.astimezone()
    assert (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0)
    assert timedelta(0) <= created - plan.start < timedelta(days=1)
    assert plan.end == NOW and plan.cursor is None
    assert len(plan.chunks) == math.ceil((NOW - plan.start) / BACKFILL_CHUNK) >= 3
    assert plan.chunks[0].start == plan.start and plan.chunks[-1].end == NOW
    for before, after in zip(plan.chunks, plan.chunks[1:], strict=False):
        assert before.end == after.start  # contiguous, no overlap
        assert before.end - before.start == BACKFILL_CHUNK
    assert plan.chunks[-1].end - plan.chunks[-1].start <= BACKFILL_CHUNK
    assert plan.covers_history and plan.earlier == ()


def test_plan_end_is_the_cursor_and_overrides_only_narrow_it(conn) -> None:
    fake = history_aw(NOW)
    cursor = NOW - timedelta(days=5)
    set_cursor(conn, WINDOW_SOURCE, cursor)
    assert window_plan(fake, conn).end == cursor
    assert window_plan(fake, conn, end=NOW).end == cursor  # clamped to the cursor
    early = NOW - timedelta(days=12)
    start = NOW - timedelta(days=15)
    plan = window_plan(fake, conn, start=start, end=early)
    assert (plan.start, plan.end) == (start, early)
    assert plan.chunks == ((start, early),)
    nothing = window_plan(fake, conn, start=cursor + timedelta(hours=1))
    assert nothing.chunks == ()


def test_plan_without_created_times_has_no_start(conn) -> None:
    fake = history_aw(NOW)
    del fake.buckets[WINDOW_BUCKET]["created"]
    plan = window_plan(fake, conn)
    assert plan.start is None and plan.chunks == () and not plan.covers_history
    # An explicit start still works.
    assert window_plan(fake, conn, start=NOW - timedelta(days=1)).chunks


def test_plan_probe_ignores_an_event_at_the_start_but_finds_one_before(conn) -> None:
    fake = FakeAW({WINDOW_BUCKET: "currentwindow"}, t0=NOW - timedelta(days=3))
    start = NOW - timedelta(days=2)
    fake.add(WINDOW_BUCKET, DAY, 60, {"app": "A"})  # exactly at `start`: first chunk's
    assert window_plan(fake, conn, start=start).earlier == ()
    early = fake.add(WINDOW_BUCKET, DAY - 60, 60, {"app": "B"})  # hidden behind it if
    plan = window_plan(fake, conn, start=start)  # the probe's end were inclusive
    assert plan.earlier == ((WINDOW_BUCKET, to_utc(early["timestamp"])),)
    assert not plan.covers_history


# --- running -----------------------------------------------------------------------


def test_backfill_ingests_all_history_across_chunks(conn) -> None:
    fake = history_aw(NOW)
    plan = window_plan(fake, conn)
    seen: list[tuple[int, int]] = []
    result = run_backfill(
        conn,
        fake,
        plan,
        clock=lambda: NOW,
        on_chunk=lambda i, c, o, r: seen.append((i, o.inserted)),
    )
    assert [i for i, _ in seen] == list(range(len(plan.chunks)))
    assert sum(n for _, n in seen) == result.inserted == DAYS
    assert result.chunks_done == len(plan.chunks)
    assert result.held_back == 1
    assert len(stored(conn, WINDOW_SOURCE)) == DAYS


def test_event_straddling_a_chunk_edge_is_stored_once_and_whole(conn) -> None:
    fake = history_aw(NOW)
    plan = window_plan(fake, conn)
    edge = plan.chunks[0].end
    offset = (edge - fake.t0) / timedelta(minutes=1)
    straddler = fake.add(WINDOW_BUCKET, offset - 60, 3 * 3600, {"app": "Long"})
    on_edge = fake.add(WINDOW_BUCKET, offset, 30, {"app": "Edge"})
    first = backfill(conn, fake, plan)
    assert first.inserted == DAYS + 2

    rows = {row["source_id"]: row for row in stored(conn, WINDOW_SOURCE)}
    long_row = rows[f"{WINDOW_BUCKET}/{straddler['id']}"]
    assert to_utc(long_row["ended_at"]) - to_utc(long_row["started_at"]) == timedelta(hours=3)
    assert to_utc(rows[f"{WINDOW_BUCKET}/{on_edge['id']}"]["started_at"]) == edge

    again = backfill(conn, fake, window_plan(fake, conn, start=plan.start))
    assert (again.inserted, again.skipped) == (0, DAYS + 2)
    assert len(stored(conn, WINDOW_SOURCE)) == DAYS + 2


class RecordingAW(FakeAW):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.queries: list[dict[str, Any]] = []

    def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.queries.append(kwargs)
        return super().get_events(bucket_id, **kwargs)


def test_cursor_set_to_final_frontier_so_ingest_does_not_rescan_history(conn) -> None:
    fake = RecordingAW({WINDOW_BUCKET: "currentwindow"}, t0=NOW - timedelta(days=DAYS))
    fake.events = {WINDOW_BUCKET: history_aw(NOW).events[WINDOW_BUCKET]}
    held_start = NOW - timedelta(minutes=5)
    plan = window_plan(fake, conn)
    result = backfill(conn, fake, plan)

    assert result.incomplete == [(plan.chunks[-1], held_start)]
    assert result.complete_until == held_start
    assert result.cursor_set
    assert to_utc(get_cursor(conn, WINDOW_SOURCE)) == held_start

    fake.queries.clear()
    later = ingest_source(conn, fake, WINDOW, now=NOW + timedelta(minutes=10))
    assert later.inserted == 1  # the held event, now settled
    range_queries = [q for q in fake.queries if q.get("limit") == -1]
    overlap = timedelta(seconds=CURSOR_OVERLAP_SECONDS)
    assert [to_utc(q["start"]) for q in range_queries] == [
        held_start - overlap - timedelta(seconds=1)
    ]


def test_existing_cursor_bounds_the_range_and_is_not_moved(conn) -> None:
    fake = history_aw(NOW)
    cursor = NOW - timedelta(days=10, hours=12)
    set_cursor(conn, WINDOW_SOURCE, cursor)
    result = backfill(conn, fake, window_plan(fake, conn))
    assert not result.cursor_set and result.incomplete == []
    assert to_utc(get_cursor(conn, WINDOW_SOURCE)) == cursor
    starts = [to_utc(row["started_at"]) for row in stored(conn, WINDOW_SOURCE)]
    assert len(starts) == 10 and max(starts) < cursor


def test_history_before_the_floor_is_reported_and_leaves_the_cursor_unset(conn) -> None:
    fake = history_aw(NOW)
    imported = fake.add(WINDOW_BUCKET, -3 * DAY, 60, {"app": "Imported"})
    plan = window_plan(fake, conn)
    assert plan.earlier == ((WINDOW_BUCKET, to_utc(imported["timestamp"])),)
    result = backfill(conn, fake, plan)
    assert result.inserted == DAYS and not result.cursor_set
    assert get_cursor(conn, WINDOW_SOURCE) is None  # the next ingest reads from the beginning

    wider = window_plan(fake, conn, start=NOW - timedelta(days=DAYS + 5))
    assert wider.covers_history
    result = backfill(conn, fake, wider)
    assert (result.inserted, result.cursor_set) == (1, True)


def test_a_cursor_set_meanwhile_wins(conn) -> None:
    fake = history_aw(NOW)
    plan = window_plan(fake, conn)  # planned without a cursor
    concurrent = NOW - timedelta(minutes=30)
    set_cursor(conn, WINDOW_SOURCE, concurrent)  # e.g. by `ingest --watch`
    result = backfill(conn, fake, plan)
    assert not result.cursor_set
    assert to_utc(get_cursor(conn, WINDOW_SOURCE)) == concurrent


def test_init_cursor_only_sets_an_absent_cursor(conn) -> None:
    assert init_cursor(conn, WINDOW_SOURCE, NOW) is True
    assert init_cursor(conn, WINDOW_SOURCE, NOW - timedelta(days=1)) is False
    assert to_utc(get_cursor(conn, WINDOW_SOURCE)) == NOW


# --- CLI ---------------------------------------------------------------------------


@pytest.fixture
def use_aw(monkeypatch: pytest.MonkeyPatch):
    def install(fake: FakeAW) -> FakeAW:
        monkeypatch.setattr(cli, "AWClient", lambda *args, **kwargs: fake)
        return fake

    return install


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def chunk_lines(out: str, source: str) -> list[str]:
    return [line for line in out.splitlines() if re.match(rf"\s+{source} chunk\s+\d+/\d+", line)]


def expected_chunks(fake: FakeAW, now: datetime) -> int:
    source = discover_sources(fake)[0]
    return len(plan_backfill(fake, source, cursor=None, now=now).chunks)


def test_cli_backfill_creates_store_prints_progress_and_totals(
    capsys, use_aw, db_path: Path
) -> None:
    now = datetime.now(UTC)
    fake = use_aw(history_aw(now))
    assert not db_path.exists()  # backfill may be the very first command
    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 0, out
    total = expected_chunks(fake, now)
    for source in (AFK_SOURCE, WINDOW_SOURCE):
        lines = chunk_lines(out, source)
        assert len(lines) == total >= 3
        assert all(f"/{total}  [" in line for line in lines)
        assert re.search(rf"{source} done in .*: inserted {DAYS}, skipped 0, held back 1", out)
        assert re.search(rf"{source}\s+chunks\s+{total}\s+inserted\s+{DAYS}\s+skipped\s+0", out)
    assert "Backfill totals:" in out
    assert out.count("cursor set to") == 2
    conn = connect(db_path)
    try:
        assert table_counts(conn)["observations"] == 2 * DAYS
        assert table_counts(conn)["ingest_cursors"] == 2
    finally:
        conn.close()


def test_cli_backfill_reports_the_held_back_final_chunk(capsys, use_aw, db_path: Path) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    _, out, _ = run(capsys, "--db-path", str(db_path), "backfill")
    last = chunk_lines(out, WINDOW_SOURCE)[-1]
    assert re.search(r"held back\s+1 .*incomplete from ", last)
    assert all("incomplete" not in line for line in chunk_lines(out, WINDOW_SOURCE)[:-1])
    assert re.search(r"note: aw-window events from .* had not settled yet \(held back\)", out)


def test_cli_backfill_rerun_inserts_nothing(capsys, use_aw, db_path: Path) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    run(capsys, "--db-path", str(db_path), "backfill")
    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 0
    lines = chunk_lines(out, WINDOW_SOURCE) + chunk_lines(out, AFK_SOURCE)
    assert lines and all(re.search(r"inserted\s+0\s", line) for line in lines)
    assert re.search(rf"aw-window\s+chunks\s+\d+\s+inserted\s+0\s+skipped\s+{DAYS}", out)
    assert "cursor unchanged at" in out
    conn = connect(db_path)
    try:
        assert table_counts(conn)["observations"] == 2 * DAYS
    finally:
        conn.close()


def test_cli_dry_run_creates_nothing_and_lists_chunks(capsys, use_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    fake = use_aw(history_aw(now))
    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill", "--dry-run")
    assert code == 0
    assert not db_path.exists()
    total = expected_chunks(fake, now)
    assert len(re.findall(rf"^\s+chunk\s+\d+/{total}  \[", out, re.MULTILINE)) == 2 * total
    assert "up to now (no cursor yet)" in out
    assert "dry run: nothing written" in out


def test_cli_dry_run_on_existing_store_writes_nothing_and_uses_the_cursor(
    capsys, use_aw, db_path: Path
) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    conn = connect(db_path)
    set_cursor(conn, WINDOW_SOURCE, datetime.now(UTC) - timedelta(days=3))
    before = table_counts(conn)
    conn.close()
    mtime = db_path.stat().st_mtime_ns

    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill", "--dry-run")
    assert code == 0
    assert "aw-window (1 bucket):" in out and "up to its cursor" in out
    assert db_path.stat().st_mtime_ns == mtime
    conn = connect(db_path)
    try:
        assert table_counts(conn) == before
    finally:
        conn.close()


def test_cli_start_end_overrides(capsys, use_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    use_aw(history_aw(now))
    start = (now - timedelta(days=3)).isoformat()
    end = (now - timedelta(days=1)).isoformat()
    code, out, _ = run(
        capsys, "--db-path", str(db_path), "backfill", "--start", start, "--end", end
    )
    assert code == 0
    assert len(chunk_lines(out, WINDOW_SOURCE)) == 1
    assert re.search(r"aw-window\s+chunks\s+1\s+inserted\s+2\s", out)  # days 17, 18
    # The range misses earlier history: the cursor must not claim it is stored.
    assert "cursor not set" in out
    conn = connect(db_path)
    try:
        assert get_cursor(conn, WINDOW_SOURCE) is None
    finally:
        conn.close()


def test_cli_rejects_bad_ranges(capsys, use_aw, db_path: Path) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    with pytest.raises(SystemExit) as exc:
        cli.main(["--db-path", str(db_path), "backfill", "--start", "last tuesday"])
    assert exc.value.code == 2
    assert "not an ISO date" in capsys.readouterr().err
    code, _, err = run(
        capsys,
        "--db-path",
        str(db_path),
        "backfill",
        "--start",
        "2026-11-10",
        "--end",
        "2026-11-01",
    )
    assert code == 2 and "--start must be before --end" in err
    assert not db_path.exists()


def test_when_arg_reads_naive_values_as_local_time() -> None:
    parsed = cli._when_arg("2026-11-01")
    assert parsed.tzinfo is UTC
    assert parsed == datetime(2026, 11, 1).astimezone().astimezone(UTC)
    assert cli._when_arg("2026-11-01T09:00+00:00") == datetime(2026, 11, 1, 9, tzinfo=UTC)


class DownAW(FakeAW):
    def get_buckets(self) -> dict[str, dict[str, Any]]:
        raise AWError("ActivityWatch unreachable at http://127.0.0.1:5600/api/0: refused")


def test_cli_backfill_with_aw_down_creates_nothing(capsys, use_aw, db_path: Path) -> None:
    use_aw(DownAW({}))
    code, _, err = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 1
    assert "ActivityWatch unreachable" in err and "Is ActivityWatch running?" in err
    assert "Committed chunks are kept" not in err
    assert "Traceback" not in err
    assert not db_path.exists()


class FailingAW(FakeAW):
    """Fails every range query after the first ``ok`` of them."""

    def __init__(self, *args: Any, ok: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.ok = ok

    def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        if kwargs.get("limit") == -1:
            if self.ok == 0:
                raise AWError("ActivityWatch HTTP 500 for /events")
            self.ok -= 1
        return super().get_events(bucket_id, **kwargs)


def test_cli_backfill_mid_run_failure_keeps_committed_chunks(capsys, use_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    healthy = history_aw(now)
    fake = FailingAW({WINDOW_BUCKET: "currentwindow"}, t0=healthy.t0, ok=2)
    fake.events = {WINDOW_BUCKET: healthy.events[WINDOW_BUCKET]}
    use_aw(fake)
    code, out, err = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 1
    assert len(chunk_lines(out, WINDOW_SOURCE)) == 2
    assert re.search(r"aw-window\s+chunks\s+2\s+inserted", out)  # partial totals
    assert "HTTP 500" in err and "re-run `computer-history backfill`" in err
    conn = connect(db_path)
    try:
        assert 0 < table_counts(conn)["observations"] < DAYS
        assert get_cursor(conn, WINDOW_SOURCE) is None  # unfinished: no cursor claim
    finally:
        conn.close()


def test_cli_backfill_on_a_locked_store_fails_cleanly(
    capsys, use_aw, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    locker = connect(db_path)

    def quick_connect(path: Any) -> sqlite3.Connection:
        conn = connect(path)
        conn.execute("PRAGMA busy_timeout = 50")  # don't wait the full 5s in a test
        return conn

    monkeypatch.setattr(cli, "connect", quick_connect)
    try:
        locker.execute("BEGIN IMMEDIATE")
        code, _, err = run(capsys, "--db-path", str(db_path), "backfill")
    finally:
        locker.execute("ROLLBACK")
        locker.close()
    assert code == 1
    assert "database is locked" in err
    assert "Is another process writing to" in err
    assert "Committed chunks are kept" not in err  # nothing was committed
    assert "Traceback" not in err


def test_backfill_help_lists_its_flags(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["backfill", "--help"])
    out = capsys.readouterr().out
    for flag in ("--start", "--end", "--dry-run", "--db-path", "--aw-url"):
        assert flag in out


def test_unreadable_event_before_the_start_fails_safe(conn, caplog) -> None:
    fake = history_aw(NOW)
    fake.events[WINDOW_BUCKET].append(
        {"id": 999, "timestamp": "not a time", "duration": 1, "data": {}}
    )
    plan = window_plan(fake, conn)
    assert plan.earlier == ((WINDOW_BUCKET, None),)
    assert not plan.covers_history
    assert "malformed ActivityWatch event in " + WINDOW_BUCKET in caplog.text
    result = backfill(conn, fake, plan)
    assert result.inserted == DAYS and not result.cursor_set
    assert get_cursor(conn, WINDOW_SOURCE) is None


def test_cli_warns_about_unreadable_earlier_history(capsys, use_aw, db_path: Path) -> None:
    fake = use_aw(history_aw(datetime.now(UTC)))
    fake.events[WINDOW_BUCKET].append({"id": 999, "timestamp": "??", "duration": 1, "data": {}})
    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill", "--dry-run")
    assert code == 0
    assert "the newest has an unreadable timestamp" in out
    assert "cursor will not be set" in out


class CountingAW(FakeAW):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.listings = 0

    def get_buckets(self) -> dict[str, dict[str, Any]]:
        self.listings += 1
        return super().get_buckets()


def test_cli_lists_buckets_once_per_run(capsys, use_aw, db_path: Path) -> None:
    healthy = history_aw(datetime.now(UTC))
    fake = CountingAW({WINDOW_BUCKET: "currentwindow", AFK_BUCKET: "afkstatus"}, t0=healthy.t0)
    fake.events = healthy.events
    use_aw(fake)
    assert run(capsys, "--db-path", str(db_path), "backfill")[0] == 0
    assert fake.listings == 1


class ProbeFailsAW(FakeAW):
    def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        raise AWError("ActivityWatch HTTP 500 for /events")


def test_cli_planning_failure_creates_nothing_and_claims_no_progress(
    capsys, use_aw, db_path: Path
) -> None:
    use_aw(ProbeFailsAW({WINDOW_BUCKET: "currentwindow"}, t0=NOW - timedelta(days=3)))
    code, out, err = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 1
    assert "HTTP 500" in err
    assert "Committed chunks are kept" not in err
    assert "Backfill totals" not in out
    assert not db_path.exists()


def test_cli_hard_database_error_mid_run_reports_totals_and_resume_hint(
    capsys, use_aw, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    real_ingest = backfill_module.ingest_source
    calls = 0

    def corrupt_after_one(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise sqlite3.DatabaseError("database disk image is malformed")
        return real_ingest(*args, **kwargs)

    monkeypatch.setattr(backfill_module, "ingest_source", corrupt_after_one)
    code, out, err = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 1
    assert re.search(r"aw-afk\s+chunks\s+1\s+inserted", out)
    assert "database error: database disk image is malformed" in err
    assert "Is another process writing to" not in err  # not a lock problem
    assert "Committed chunks are kept" in err
    assert "Traceback" not in err


def test_unhandled_command_fails_cleanly(capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(cli.COMMANDS, "frobnicate", "Not built yet.")
    assert cli.main(["frobnicate"]) == 1
    assert "computer-history frobnicate: not implemented yet" in capsys.readouterr().err
