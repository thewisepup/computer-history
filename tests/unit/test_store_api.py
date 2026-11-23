import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest
from projectors import payload_fields

from computer_history.store import (
    Gap,
    InsertResult,
    Observation,
    ProgressUpdate,
    UnclaimedSource,
    find_gaps,
    get_progress,
    insert_observations,
    source_summary,
    table_counts,
    transaction,
)

T0 = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def window(source_id: str, start: float = 0, end: float = 1, title: str = "t") -> Observation:
    return Observation(
        source="aw-window",
        source_id=source_id,
        started_at=at(start),
        ended_at=at(end),
        payload=json.dumps({"app": "Code", "title": title}),
    )


def afk(source_id: str, start: float = 0, end: float = 1) -> Observation:
    return Observation("aw-afk", source_id, at(start), at(end), '{"status": "afk"}')


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def advance(source: str, minutes: float) -> ProgressUpdate:
    return ProgressUpdate(source, f"pos-{minutes}", settled_until=at(minutes))


def settled(conn: sqlite3.Connection, source: str) -> datetime | None:
    progress = get_progress(conn, source)
    return None if progress is None else progress.settled_until


def test_insert_writes_observation_and_signal(conn: sqlite3.Connection) -> None:
    result = insert_observations(conn, [window("1", title="hello")], project=payload_fields)
    assert result == InsertResult(inserted=1, skipped=0)
    obs = conn.execute("SELECT * FROM observations").fetchone()
    sig = conn.execute("SELECT * FROM signals").fetchone()
    assert obs["payload"] == '{"app": "Code", "title": "hello"}'
    assert sig["observation_id"] == obs["id"]
    assert (sig["source"], sig["started_at"], sig["ended_at"]) == (
        obs["source"],
        obs["started_at"],
        obs["ended_at"],
    )
    assert (sig["app"], sig["title"], sig["url"]) == ("Code", "hello", None)


def test_reinsert_adds_zero_rows(conn: sqlite3.Connection) -> None:
    batch = [window("1"), window("2"), afk("1")]
    assert insert_observations(conn, batch, project=payload_fields) == InsertResult(3, 0)
    assert insert_observations(conn, batch, project=payload_fields) == InsertResult(0, 3)
    assert count(conn, "observations") == 3
    assert count(conn, "signals") == 2


def test_duplicate_in_same_batch_is_skipped(conn: sqlite3.Connection) -> None:
    assert insert_observations(
        conn, [window("1"), window("1"), window("2")], project=payload_fields
    ) == InsertResult(2, 1)


def test_same_source_id_in_different_sources_is_not_a_duplicate(
    conn: sqlite3.Connection,
) -> None:
    assert insert_observations(
        conn, [window("1"), afk("1")], project=payload_fields
    ) == InsertResult(2, 0)


def test_mixed_new_and_duplicate_batch(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("1")], project=payload_fields)
    assert insert_observations(
        conn, [window("1"), window("2")], project=payload_fields
    ) == InsertResult(1, 1)
    assert count(conn, "observations") == count(conn, "signals") == 2


def test_duplicate_never_overwrites_existing_signal(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("1", title="original")], project=payload_fields)
    insert_observations(conn, [window("1", title="changed")], project=payload_fields)
    titles = [row[0] for row in conn.execute("SELECT title FROM signals")]
    assert titles == ["original"]


def test_afk_observation_gets_no_signal(conn: sqlite3.Connection) -> None:
    assert insert_observations(conn, [afk("1")], project=payload_fields) == InsertResult(1, 0)
    assert count(conn, "observations") == 1
    assert count(conn, "signals") == 0


def test_empty_batch(conn: sqlite3.Connection) -> None:
    assert insert_observations(conn, [], project=payload_fields) == InsertResult(0, 0)


def test_generator_input(conn: sqlite3.Connection) -> None:
    assert insert_observations(
        conn, (window(str(i)) for i in range(3)), project=payload_fields
    ) == InsertResult(3, 0)


def test_timestamps_stored_canonically(conn: sqlite3.Connection) -> None:
    obs = Observation(
        source="aw-window",
        source_id="1",
        started_at="2026-11-17T11:00:00+01:00",
        ended_at="2026-11-17T10:01:30.5Z",
        payload='{"app": "Code"}',
    )
    progress = ProgressUpdate("aw-window", "p", settled_until="2026-11-17T05:01:30-05:00")
    insert_observations(conn, [obs], progress=progress, project=payload_fields)
    o = conn.execute("SELECT started_at, ended_at, ingested_at FROM observations").fetchone()
    s = conn.execute("SELECT started_at, ended_at FROM signals").fetchone()
    canonical = ("2026-11-17T10:00:00.000000Z", "2026-11-17T10:01:30.500000Z")
    assert tuple(o[:2]) == tuple(s) == canonical
    assert len(o["ingested_at"]) == len("2026-11-17T10:00:00.000000Z")
    assert o["ingested_at"].endswith("Z")
    stored = conn.execute("SELECT settled_until, advanced_at FROM ingest_progress").fetchone()
    assert stored["settled_until"] == "2026-11-17T10:01:30.000000Z"
    assert stored["advanced_at"] == o["ingested_at"]


@pytest.mark.parametrize(
    "bad",
    [
        Observation("aw-window", "", at(0), at(1), "{}"),
        Observation("aw-window", None, at(0), at(1), "{}"),  # pyright: ignore[reportArgumentType]
        Observation("aw-window", "1", at(1), at(0), "{}"),
        Observation("aw-window", "1", "2026-11-17T10:00:00", at(1), "{}"),
    ],
    ids=["empty-id", "null-id", "ends-before-start", "naive-timestamp"],
)
def test_invalid_observation_rejects_whole_batch(
    conn: sqlite3.Connection, bad: Observation
) -> None:
    with pytest.raises(ValueError):
        insert_observations(conn, [window("ok"), bad], project=payload_fields)
    assert count(conn, "observations") == 0


def fail_signal_titled(conn: sqlite3.Connection, title: str) -> None:
    conn.execute(
        f"""
        CREATE TEMP TRIGGER fail_signal BEFORE INSERT ON main.signals
        WHEN NEW.title = '{title}'
        BEGIN SELECT RAISE(ABORT, 'injected signal failure'); END
        """
    )


def test_failed_signal_rolls_back_whole_batch_and_progress(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [], progress=advance("aw-window", 0), project=payload_fields)
    before = get_progress(conn, "aw-window")
    fail_signal_titled(conn, "boom")
    batch = [window("1"), window("2", title="boom"), window("3")]

    with pytest.raises(sqlite3.IntegrityError, match="injected signal failure"):
        insert_observations(conn, batch, progress=advance("aw-window", 5), project=payload_fields)

    assert not conn.in_transaction
    assert count(conn, "observations") == 0
    assert count(conn, "signals") == 0
    assert get_progress(conn, "aw-window") == before


def test_failed_batch_rolls_back_first_progress(conn: sqlite3.Connection) -> None:
    fail_signal_titled(conn, "boom")
    first = ProgressUpdate("aw-window", "p", settled_until=at(5), only_if_none=True)
    with pytest.raises(sqlite3.IntegrityError):
        insert_observations(
            conn, [window("1", title="boom")], progress=first, project=payload_fields
        )
    assert get_progress(conn, "aw-window") is None


def test_unclaimed_source_rolls_back_whole_batch_and_progress(conn: sqlite3.Connection) -> None:
    def claims_windows_only(source: str, payload: str):
        if source != "aw-window":
            raise UnclaimedSource(source)
        return payload_fields(source, payload)

    with pytest.raises(UnclaimedSource, match="'aw-afk'"):
        insert_observations(
            conn,
            [window("1"), afk("1")],
            progress=advance("aw-afk", 1),
            project=claims_windows_only,
        )
    assert count(conn, "observations") == count(conn, "signals") == 0
    assert get_progress(conn, "aw-afk") is None


def test_retry_after_failure_succeeds(conn: sqlite3.Connection) -> None:
    fail_signal_titled(conn, "boom")
    batch = [window("1"), window("2", title="boom")]
    with pytest.raises(sqlite3.IntegrityError):
        insert_observations(conn, batch, progress=advance("aw-window", 5), project=payload_fields)
    conn.execute("DROP TRIGGER temp.fail_signal")

    assert insert_observations(
        conn, batch, progress=advance("aw-window", 5), project=payload_fields
    ) == (2, 0, True)
    assert settled(conn, "aw-window") == at(5)


def test_progress_advances_with_batch(conn: sqlite3.Connection) -> None:
    result = insert_observations(
        conn, [window("1")], progress=advance("aw-window", 1), project=payload_fields
    )
    assert result == InsertResult(inserted=1, skipped=0, progress_moved=True)
    assert settled(conn, "aw-window") == at(1)


def test_progress_advances_even_when_batch_is_all_duplicates(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("1")], project=payload_fields)
    insert_observations(
        conn, [window("1")], progress=advance("aw-window", 9), project=payload_fields
    )
    assert settled(conn, "aw-window") == at(9)


def test_insert_inside_open_transaction_is_refused(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO work_types (name, status, created_at) VALUES ('kept', 'active', 'now')"
        )
        with pytest.raises(RuntimeError, match="inside transaction"):
            insert_observations(conn, [window("1")], project=payload_fields)
    assert count(conn, "observations") == 0
    assert count(conn, "work_types") == 1


def test_source_summary(conn: sqlite3.Connection) -> None:
    assert source_summary(conn) == []
    insert_observations(
        conn,
        [window("1", 0, 5), window("2", 1, 3)],
        progress=advance("aw-window", 5),
        project=payload_fields,
    )
    insert_observations(conn, [afk("1", 0, 2), afk("2", -3, -1)], project=payload_fields)
    insert_observations(
        conn, [], progress=ProgressUpdate("aw-web", "spool.jsonl:0"), project=payload_fields
    )

    rows = {row.source: row for row in source_summary(conn)}
    assert list(rows) == ["aw-afk", "aw-web", "aw-window"]
    assert rows["aw-window"][:5] == ("aw-window", 2, at(0), at(5), at(5))
    assert rows["aw-afk"] == ("aw-afk", 2, at(-3), at(2), None, None)
    assert rows["aw-web"][:5] == ("aw-web", 0, None, None, None)
    assert rows["aw-web"].advanced_at is not None
    latest = rows["aw-window"].latest_ended_at
    assert latest is not None and latest.tzinfo is not None


def test_table_counts(conn: sqlite3.Connection) -> None:
    insert_observations(
        conn, [window("1"), afk("1")], progress=advance("aw-afk", 1), project=payload_fields
    )
    counts = table_counts(conn)
    assert counts["observations"] == 2
    assert counts["signals"] == 1
    assert counts["ingest_progress"] == 1
    assert counts["blocks"] == 0
    assert "sqlite_sequence" not in counts


def gaps(conn: sqlite3.Connection, start: float, end: float, **kw) -> list[tuple[float, float]]:
    result = find_gaps(conn, "aw-window", at(start), at(end), **kw)
    assert all(isinstance(gap, Gap) for gap in result)
    minute = timedelta(minutes=1)
    return [((g.start - T0) / minute, (g.end - T0) / minute) for g in result]


def test_gaps_whole_range_when_no_observations(conn: sqlite3.Connection) -> None:
    assert gaps(conn, 0, 60) == [(0, 60)]


def test_no_gaps_when_continuous(conn: sqlite3.Connection) -> None:
    insert_observations(
        conn,
        [window("1", -5, 20), window("2", 20, 40), window("3", 40, 70)],
        project=payload_fields,
    )
    assert gaps(conn, 0, 60) == []


def test_gaps_merge_overlapping_observations(conn: sqlite3.Connection) -> None:
    insert_observations(
        conn,
        [window("a", 10, 30), window("b", 15, 25), window("c", 20, 35), window("d", 45, 50)],
        project=payload_fields,
    )
    assert gaps(conn, 0, 60) == [(0, 10), (35, 45), (50, 60)]


def test_gaps_at_range_edges_are_clipped(conn: sqlite3.Connection) -> None:
    insert_observations(
        conn, [window("before", -30, 5), window("after", 55, 90)], project=payload_fields
    )
    assert gaps(conn, 0, 60) == [(5, 55)]


def test_gaps_ignore_observations_outside_range(conn: sqlite3.Connection) -> None:
    insert_observations(
        conn, [window("before", -30, 0), window("after", 60, 90)], project=payload_fields
    )
    assert gaps(conn, 0, 60) == [(0, 60)]


def test_gaps_ignore_other_sources(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [afk("1", 0, 60)], project=payload_fields)
    assert gaps(conn, 0, 60) == [(0, 60)]


def test_zero_length_observation_does_not_split_a_gap(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("instant", 30, 30)], project=payload_fields)
    assert gaps(conn, 0, 60, min_gap_seconds=45 * 60) == [(0, 60)]


def test_gaps_min_length_filter(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("a", 1, 30), window("b", 31, 50)], project=payload_fields)
    assert gaps(conn, 0, 60) == [(0, 1), (30, 31), (50, 60)]
    assert gaps(conn, 0, 60, min_gap_seconds=120) == [(50, 60)]


def test_gaps_accept_bounds_in_any_time_zone_and_reject_empty_range(
    conn: sqlite3.Connection,
) -> None:
    paris = timezone(timedelta(hours=1))
    result = find_gaps(conn, "aw-window", datetime(2026, 11, 17, 11, 0, tzinfo=paris), at(30))
    assert result == [Gap(at(0), at(30))]
    assert result[0].seconds == 1800
    with pytest.raises(ValueError, match="empty"):
        find_gaps(conn, "aw-window", at(5), at(5))
