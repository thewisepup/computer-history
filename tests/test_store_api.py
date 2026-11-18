import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from computer_history.store import (
    Cursor,
    Gap,
    InsertResult,
    Observation,
    Signal,
    find_gaps,
    get_cursor,
    insert_observations,
    set_cursor,
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
        payload='{"app": "Code"}',
        signal=Signal(app="Code", title=title),
    )


def afk(source_id: str, start: float = 0, end: float = 1) -> Observation:
    return Observation("aw-afk", source_id, at(start), at(end), '{"status": "afk"}')


def count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- insert_observations -------------------------------------------------------


def test_insert_writes_observation_and_signal(conn: sqlite3.Connection) -> None:
    result = insert_observations(conn, [window("1", title="hello")])
    assert result == InsertResult(inserted=1, skipped=0)
    obs = conn.execute("SELECT * FROM observations").fetchone()
    sig = conn.execute("SELECT * FROM signals").fetchone()
    assert obs["payload"] == '{"app": "Code"}'
    assert sig["observation_id"] == obs["id"]
    assert (sig["source"], sig["started_at"], sig["ended_at"]) == (
        obs["source"],
        obs["started_at"],
        obs["ended_at"],
    )
    assert (sig["app"], sig["title"], sig["url"]) == ("Code", "hello", None)


def test_reinsert_adds_zero_rows(conn: sqlite3.Connection) -> None:
    batch = [window("1"), window("2"), afk("1")]
    assert insert_observations(conn, batch) == (3, 0)
    assert insert_observations(conn, batch) == (0, 3)
    assert count(conn, "observations") == 3
    assert count(conn, "signals") == 2


def test_duplicate_in_same_batch_is_skipped(conn: sqlite3.Connection) -> None:
    assert insert_observations(conn, [window("1"), window("1"), window("2")]) == (2, 1)


def test_same_source_id_in_different_sources_is_not_a_duplicate(
    conn: sqlite3.Connection,
) -> None:
    assert insert_observations(conn, [window("1"), afk("1")]) == (2, 0)


def test_mixed_new_and_duplicate_batch(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("1")])
    assert insert_observations(conn, [window("1"), window("2")]) == (1, 1)
    assert count(conn, "observations") == count(conn, "signals") == 2


def test_duplicate_never_overwrites_existing_signal(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("1", title="original")])
    insert_observations(conn, [window("1", title="changed")])
    titles = [row[0] for row in conn.execute("SELECT title FROM signals")]
    assert titles == ["original"]


def test_afk_observation_gets_no_signal(conn: sqlite3.Connection) -> None:
    assert insert_observations(conn, [afk("1")]) == (1, 0)
    assert count(conn, "observations") == 1
    assert count(conn, "signals") == 0


def test_empty_batch(conn: sqlite3.Connection) -> None:
    assert insert_observations(conn, []) == (0, 0)


def test_generator_input(conn: sqlite3.Connection) -> None:
    assert insert_observations(conn, (window(str(i)) for i in range(3))) == (3, 0)


def test_timestamps_stored_canonically(conn: sqlite3.Connection) -> None:
    obs = Observation(
        source="aw-window",
        source_id="1",
        started_at="2026-11-17T11:00:00+01:00",
        ended_at="2026-11-17T10:01:30.5Z",
        payload="{}",
        signal=Signal(app="Code"),
    )
    cursor = Cursor("aw-window", "2026-11-17T05:01:30-05:00")
    insert_observations(conn, [obs], advance_cursor=cursor)
    o = conn.execute("SELECT started_at, ended_at, ingested_at FROM observations").fetchone()
    s = conn.execute("SELECT started_at, ended_at FROM signals").fetchone()
    canonical = ("2026-11-17T10:00:00.000000Z", "2026-11-17T10:01:30.500000Z")
    assert tuple(o[:2]) == tuple(s) == canonical
    assert len(o["ingested_at"]) == len("2026-11-17T10:00:00.000000Z")
    assert o["ingested_at"].endswith("Z")
    assert get_cursor(conn, "aw-window") == "2026-11-17T10:01:30.000000Z"


@pytest.mark.parametrize(
    "bad",
    [
        Observation("aw-window", "", at(0), at(1), "{}"),
        Observation("aw-window", None, at(0), at(1), "{}"),  # type: ignore[arg-type]
        Observation("aw-window", "1", at(1), at(0), "{}"),
        Observation("aw-window", "1", "2026-11-17T10:00:00", at(1), "{}"),
    ],
    ids=["empty-id", "null-id", "ends-before-start", "naive-timestamp"],
)
def test_invalid_observation_rejects_whole_batch(
    conn: sqlite3.Connection, bad: Observation
) -> None:
    with pytest.raises(ValueError):
        insert_observations(conn, [window("ok"), bad])
    assert count(conn, "observations") == 0


# --- atomicity -----------------------------------------------------------------


def fail_signal_titled(conn: sqlite3.Connection, title: str) -> None:
    conn.execute(
        f"""
        CREATE TEMP TRIGGER fail_signal BEFORE INSERT ON main.signals
        WHEN NEW.title = '{title}'
        BEGIN SELECT RAISE(ABORT, 'injected signal failure'); END
        """
    )


def test_failed_signal_rolls_back_whole_batch_and_cursor(conn: sqlite3.Connection) -> None:
    set_cursor(conn, "aw-window", at(0))
    fail_signal_titled(conn, "boom")
    batch = [window("1"), window("2", title="boom"), window("3")]

    with pytest.raises(sqlite3.IntegrityError, match="injected signal failure"):
        insert_observations(conn, batch, advance_cursor=Cursor("aw-window", at(5)))

    assert not conn.in_transaction
    assert count(conn, "observations") == 0
    assert count(conn, "signals") == 0
    assert get_cursor(conn, "aw-window") == "2026-11-17T10:00:00.000000Z"


def test_retry_after_failure_succeeds(conn: sqlite3.Connection) -> None:
    fail_signal_titled(conn, "boom")
    batch = [window("1"), window("2", title="boom")]
    with pytest.raises(sqlite3.IntegrityError):
        insert_observations(conn, batch, advance_cursor=Cursor("aw-window", at(5)))
    conn.execute("DROP TRIGGER temp.fail_signal")

    assert insert_observations(conn, batch, advance_cursor=Cursor("aw-window", at(5))) == (2, 0)
    assert get_cursor(conn, "aw-window") == "2026-11-17T10:05:00.000000Z"


def test_cursor_advances_with_batch(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("1")], advance_cursor=Cursor("aw-window", at(1)))
    assert get_cursor(conn, "aw-window") == "2026-11-17T10:01:00.000000Z"


def test_cursor_advances_even_when_batch_is_all_duplicates(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("1")])
    insert_observations(conn, [window("1")], advance_cursor=Cursor("aw-window", at(9)))
    assert get_cursor(conn, "aw-window") == "2026-11-17T10:09:00.000000Z"


def test_insert_inside_open_transaction_is_refused(conn: sqlite3.Connection) -> None:
    # Refused up front with the caller's transaction intact: a prior write in the
    # enclosing transaction must survive the refusal.
    with transaction(conn):
        set_cursor(conn, "aw-afk", "2026-11-17T10:00:00Z")
        with pytest.raises(RuntimeError, match="inside transaction"):
            insert_observations(conn, [window("1")])
    assert count(conn, "observations") == 0
    assert get_cursor(conn, "aw-afk") == "2026-11-17T10:00:00.000000Z"


# --- cursors and mapping version -------------------------------------------------


def test_cursor_round_trip_and_upsert(conn: sqlite3.Connection) -> None:
    assert get_cursor(conn, "aw-window") is None
    set_cursor(conn, "aw-window", at(1))
    set_cursor(conn, "aw-afk", "2026-11-17T10:02:00Z")
    set_cursor(conn, "aw-window", at(3))
    assert get_cursor(conn, "aw-window") == "2026-11-17T10:03:00.000000Z"
    assert get_cursor(conn, "aw-afk") == "2026-11-17T10:02:00.000000Z"
    assert count(conn, "ingest_cursors") == 2


def test_set_cursor_joins_enclosing_transaction(conn: sqlite3.Connection) -> None:
    with pytest.raises(ZeroDivisionError), transaction(conn):
        set_cursor(conn, "aw-window", at(1))
        raise ZeroDivisionError
    assert get_cursor(conn, "aw-window") is None


# --- reads ------------------------------------------------------------------------


def test_source_summary(conn: sqlite3.Connection) -> None:
    assert source_summary(conn) == []
    insert_observations(
        conn,
        [window("1", 0, 5), window("2", 1, 3)],
        advance_cursor=Cursor("aw-window", at(5)),
    )
    insert_observations(conn, [afk("1", 0, 2), afk("2", -3, -1)])
    set_cursor(conn, "aw-web", at(0))

    rows = {row.source: row for row in source_summary(conn)}
    assert list(rows) == ["aw-afk", "aw-web", "aw-window"]
    assert rows["aw-window"] == ("aw-window", 2, at(0), at(5), at(5))
    assert rows["aw-afk"] == ("aw-afk", 2, at(-3), at(2), None)
    assert rows["aw-web"] == ("aw-web", 0, None, None, at(0))
    assert rows["aw-window"].latest_ended_at.tzinfo is not None


def test_table_counts(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("1"), afk("1")], advance_cursor=Cursor("aw-afk", at(1)))
    counts = table_counts(conn)
    assert counts["observations"] == 2
    assert counts["signals"] == 1
    assert counts["ingest_cursors"] == 1
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
    insert_observations(conn, [window("1", -5, 20), window("2", 20, 40), window("3", 40, 70)])
    assert gaps(conn, 0, 60) == []


def test_gaps_merge_overlapping_observations(conn: sqlite3.Connection) -> None:
    # 10-30 and 15-25 overlap (the second is inside the first); 20-35 extends it.
    insert_observations(
        conn,
        [window("a", 10, 30), window("b", 15, 25), window("c", 20, 35), window("d", 45, 50)],
    )
    assert gaps(conn, 0, 60) == [(0, 10), (35, 45), (50, 60)]


def test_gaps_at_range_edges_are_clipped(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("before", -30, 5), window("after", 55, 90)])
    assert gaps(conn, 0, 60) == [(5, 55)]


def test_gaps_ignore_observations_outside_range(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("before", -30, 0), window("after", 60, 90)])
    assert gaps(conn, 0, 60) == [(0, 60)]


def test_gaps_ignore_other_sources(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [afk("1", 0, 60)])
    assert gaps(conn, 0, 60) == [(0, 60)]


def test_zero_length_observation_does_not_split_a_gap(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("instant", 30, 30)])
    assert gaps(conn, 0, 60, min_gap_seconds=45 * 60) == [(0, 60)]


def test_gaps_min_length_filter(conn: sqlite3.Connection) -> None:
    insert_observations(conn, [window("a", 1, 30), window("b", 31, 50)])
    assert gaps(conn, 0, 60) == [(0, 1), (30, 31), (50, 60)]
    assert gaps(conn, 0, 60, min_gap_seconds=120) == [(50, 60)]


def test_gaps_accept_string_bounds_and_reject_empty_range(conn: sqlite3.Connection) -> None:
    result = find_gaps(conn, "aw-window", "2026-11-17T11:00:00+01:00", "2026-11-17T10:30:00Z")
    assert result == [Gap(at(0), at(30))]
    assert result[0].seconds == 1800
    with pytest.raises(ValueError, match="empty"):
        find_gaps(conn, "aw-window", at(5), at(5))
