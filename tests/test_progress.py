from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fake_aw import FakeAW, at
from projectors import no_signal

from computer_history import store
from computer_history.sources import (
    RESUME_OVERLAP_SECONDS,
    WINDOW_SOURCE,
    ActivityWatch,
    AWSource,
    BackfillProgress,
    IngestOutcome,
    SourcePull,
    plan_all_backfills,
    poll,
    position_at,
    pull_source,
    run_backfill,
)
from computer_history.sources.activitywatch.pull import CLIP_GUARD
from computer_history.store import (
    InsertResult,
    Observation,
    Progress,
    ProgressUpdate,
    connect,
    get_progress,
    insert_observations,
    load_migrations,
    migrate,
    source_summary,
    to_utc,
    utc_iso,
)
from computer_history.store.progress import write_with_batch

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
WINDOW = AWSource(WINDOW_SOURCE, (WINDOW_BUCKET,))
SPOOL_POSITION = "2026-11-18T10.jsonl:48213"
PROGRESS_MIGRATION = next(m for m in load_migrations() if m.name.endswith("_ingest_progress.sql"))


def text_capture(source_id: str, start: float, end: float) -> Observation:
    return Observation("ax-text", source_id, at(start), at(end), '{"text": "hello"}')


def test_store_round_trips_an_opaque_position_with_settled_until_set_separately(
    conn: sqlite3.Connection,
) -> None:
    update = ProgressUpdate("ax-text", SPOOL_POSITION, settled_until="2026-11-17T05:30:00-05:00")
    result = insert_observations(
        conn, [text_capture("c1", 0, 0)], progress=update, now=at(40), project=no_signal
    )
    assert result == InsertResult(inserted=1, skipped=0, progress_moved=True)
    progress = get_progress(conn, "ax-text")
    assert progress is not None
    settled = datetime(2026, 11, 17, 10, 30, tzinfo=UTC)
    assert (progress.position, progress.settled_until) == (SPOOL_POSITION, settled)
    assert progress.advanced_at == at(40)


def test_position_without_a_settled_time_is_kept(conn: sqlite3.Connection) -> None:
    insert_observations(
        conn, [], progress=ProgressUpdate("ax-text", SPOOL_POSITION), project=no_signal
    )
    progress = get_progress(conn, "ax-text")
    assert progress is not None
    assert (progress.position, progress.settled_until) == (SPOOL_POSITION, None)


def test_advance_replaces_the_previous_progress(conn: sqlite3.Connection) -> None:
    insert_observations(
        conn, [], progress=ProgressUpdate("ax-text", "a.jsonl:10"), project=no_signal
    )
    insert_observations(
        conn, [], progress=ProgressUpdate("ax-text", "b.jsonl:0", at(9)), project=no_signal
    )
    progress = get_progress(conn, "ax-text")
    assert progress is not None
    assert (progress.position, progress.settled_until) == ("b.jsonl:0", at(9))


@pytest.mark.parametrize("settled_until", [None, at(5)], ids=["no-settled-time", "settled"])
def test_repeating_the_same_progress_does_not_refresh_it(
    conn: sqlite3.Connection, settled_until: datetime | None
) -> None:
    update = ProgressUpdate("ax-text", SPOOL_POSITION, settled_until)
    assert insert_observations(
        conn, [], progress=update, now=at(10), project=no_signal
    ).progress_moved
    again = insert_observations(
        conn, [text_capture("c1", 0, 1)], progress=update, now=at(20), project=no_signal
    )
    assert again == InsertResult(inserted=1, skipped=0, progress_moved=False)
    progress = get_progress(conn, "ax-text")
    assert progress is not None and progress.advanced_at == at(10)


@pytest.mark.parametrize(
    "changed",
    [
        ProgressUpdate("ax-text", "b.jsonl:0", at(5)),
        ProgressUpdate("ax-text", SPOOL_POSITION, at(6)),
        ProgressUpdate("ax-text", SPOOL_POSITION),
    ],
    ids=["position", "settled-until", "settled-until-cleared"],
)
def test_a_changed_position_or_settled_time_refreshes_progress(
    conn: sqlite3.Connection, changed: ProgressUpdate
) -> None:
    first = ProgressUpdate("ax-text", SPOOL_POSITION, at(5))
    insert_observations(conn, [], progress=first, now=at(10), project=no_signal)
    assert insert_observations(
        conn, [], progress=changed, now=at(20), project=no_signal
    ).progress_moved
    progress = get_progress(conn, "ax-text")
    assert progress is not None and progress.advanced_at == at(20)


def test_set_if_none_sets_absent_progress(conn: sqlite3.Connection) -> None:
    first = ProgressUpdate("ax-text", SPOOL_POSITION, at(5), only_if_none=True)
    assert insert_observations(
        conn, [text_capture("c1", 0, 1)], progress=first, project=no_signal
    ).progress_moved
    progress = get_progress(conn, "ax-text")
    assert progress is not None and progress.position == SPOOL_POSITION


def test_set_if_none_never_overwrites(conn: sqlite3.Connection) -> None:
    insert_observations(
        conn, [], progress=ProgressUpdate("ax-text", "a.jsonl:10", at(1)), project=no_signal
    )
    before = get_progress(conn, "ax-text")
    first = ProgressUpdate("ax-text", "b.jsonl:0", at(9), only_if_none=True)
    result = insert_observations(
        conn, [text_capture("c1", 0, 1)], progress=first, project=no_signal
    )
    assert result == InsertResult(inserted=1, skipped=0, progress_moved=False)
    assert get_progress(conn, "ax-text") == before


def test_progress_does_not_move_outside_a_batch_transaction(conn: sqlite3.Connection) -> None:
    update = ProgressUpdate("ax-text", SPOOL_POSITION)
    with pytest.raises(RuntimeError, match="inside a batch"):
        write_with_batch(conn, update, advanced_at=utc_iso(datetime.now(UTC)))
    assert get_progress(conn, "ax-text") is None


def test_the_store_exports_no_progress_writer() -> None:
    progress_names = {name for name in store.__all__ if "progress" in name.lower()}
    assert progress_names == {"Progress", "ProgressUpdate", "get_progress"}
    assert not any("cursor" in name.lower() for name in store.__all__)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source": "", "position": "p"},
        {"source": "ax-text", "position": ""},
        {"source": "ax-text", "position": "p", "settled_until": "2026-11-17T10:00:00"},
    ],
    ids=["no-source", "no-position", "naive-settled-until"],
)
def test_bad_progress_updates_are_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ProgressUpdate(**kwargs)


def test_status_summary_reads_settled_until_for_an_opaque_position(
    conn: sqlite3.Connection,
) -> None:
    update = ProgressUpdate("ax-text", SPOOL_POSITION, settled_until=at(30))
    insert_observations(conn, [text_capture("c1", 0, 10)], progress=update, project=no_signal)
    (summary,) = source_summary(conn)
    assert summary[:5] == ("ax-text", 1, at(0), at(10), at(30))
    assert summary.advanced_at is not None


def test_backfill_plans_up_to_settled_until_for_an_opaque_position(
    conn: sqlite3.Connection,
) -> None:
    fake = FakeAW({WINDOW_BUCKET: "currentwindow"}, t0=at(-3 * 1440))
    update = ProgressUpdate(WINDOW_SOURCE, SPOOL_POSITION, settled_until=at(30))
    insert_observations(conn, [], progress=update, project=no_signal)
    (plan,) = plan_all_backfills(conn, ActivityWatch(fake), now=at(60)).plans
    assert plan.settled_until == plan.end == at(30)
    assert plan.chunks[-1].end == at(30)


def test_backfill_keeps_progress_that_has_no_settled_time(conn: sqlite3.Connection) -> None:
    fake = FakeAW({WINDOW_BUCKET: "currentwindow"}, t0=at(-3 * 1440))
    fake.add(WINDOW_BUCKET, 1440, 60, {"app": "Code"})
    insert_observations(
        conn, [], progress=ProgressUpdate(WINDOW_SOURCE, SPOOL_POSITION), project=no_signal
    )
    before = get_progress(conn, WINDOW_SOURCE)
    (plan,) = plan_all_backfills(conn, ActivityWatch(fake), now=at(60)).plans
    assert plan.has_progress and plan.settled_until is None
    assert plan.end == at(60) and plan.covers_history
    (result,) = run_backfill(conn, ActivityWatch(fake), [plan], clock=lambda: at(60)).results
    assert result.inserted == 1 and result.progress is BackfillProgress.KEPT_UNSETTLED
    assert get_progress(conn, WINDOW_SOURCE) == before


class RecordingAW(FakeAW):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.queries: list[dict[str, Any]] = []

    def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.queries.append(kwargs)
        return super().get_events(bucket_id, **kwargs)


def previous_version(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn, [m for m in load_migrations() if m.version < PROGRESS_MIGRATION.version])
    return conn


def observation_rows(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in conn.execute("SELECT * FROM observations ORDER BY id")]


def test_migration_moves_cursors_into_progress_and_leaves_observations(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    old = previous_version(path)
    insert_observations(old, [text_capture("c1", 0, 1)], project=no_signal)
    last_seen = utc_iso(at(55))
    old.execute(
        "INSERT INTO ingest_cursors (source, last_seen) VALUES (?, ?)", ("aw-afk", last_seen)
    )
    before = observation_rows(old)
    old.close()

    conn = connect(path)
    try:
        assert get_progress(conn, "aw-afk") == Progress("aw-afk", last_seen, at(55), at(55))
        assert observation_rows(conn) == before
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "ingest_cursors" not in tables
    finally:
        conn.close()


def resume_after_migration(path: Path, first_pull: SourcePull) -> sqlite3.Connection:
    old = previous_version(path)
    insert_observations(old, first_pull.observations, project=no_signal)
    old.execute(
        "INSERT INTO ingest_cursors (source, last_seen) VALUES (?, ?)",
        (WINDOW_SOURCE, utc_iso(first_pull.frontier)),
    )
    old.close()
    return connect(path)


def resume_on_current_schema(path: Path, first_pull: SourcePull) -> sqlite3.Connection:
    conn = connect(path)
    update = ProgressUpdate(
        WINDOW_SOURCE, position_at(first_pull.frontier), settled_until=first_pull.frontier
    )
    insert_observations(conn, first_pull.observations, progress=update, project=no_signal)
    return conn


@pytest.mark.parametrize("prepare", [resume_after_migration, resume_on_current_schema])
def test_migrated_cursor_resumes_like_progress_written_today(tmp_path: Path, prepare) -> None:
    fake = RecordingAW({WINDOW_BUCKET: "currentwindow"})
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    fake.add(WINDOW_BUCKET, 50, 60, {"app": "B"})
    first_pull = pull_source(fake, WINDOW, now=at(55))
    assert first_pull.frontier == at(55)
    conn = prepare(tmp_path / "history.db", first_pull)
    try:
        fake.add(WINDOW_BUCKET, 58, 60, {"app": "C"})
        fake.queries.clear()
        outcome = poll(conn, [ActivityWatch(fake)], now=at(70)).outcomes[WINDOW_SOURCE]
        assert outcome == IngestOutcome(inserted=1, skipped=1, held_back=0, settled_until=at(70))
        starts = [to_utc(q["start"]) for q in fake.queries if q.get("limit") == -1]
        overlap = timedelta(seconds=RESUME_OVERLAP_SECONDS)
        assert starts == [at(55) - overlap - CLIP_GUARD]
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 3
        progress = get_progress(conn, WINDOW_SOURCE)
        assert progress is not None and progress.settled_until == at(70)
    finally:
        conn.close()

