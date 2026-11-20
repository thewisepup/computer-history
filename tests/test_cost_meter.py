from __future__ import annotations

import sqlite3

import pytest

from computer_history.synthetic import measure

ROWS = (
    ("aw-window", "1", "2026-01-05T09:00:00.000Z", "2026-01-05T09:05:00.000Z", '{"app": "Cursor"}'),
    ("aw-window", "2", "2026-01-05T09:05:00.000Z", "2026-01-05T09:07:00.000Z", '{"app": "Slack"}'),
    ("aw-web", "3", "2026-01-05T09:05:00.000Z", "2026-01-05T09:06:00.000Z", '{"url": "x"}'),
)


@pytest.fixture
def stored(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executemany(
        "INSERT INTO observations (source, source_id, started_at, ended_at, payload, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, '2026-01-06T00:00:00.000Z')",
        ROWS,
    )
    return conn


def _read_apps(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT payload FROM observations ORDER BY id")]


def _read_apps_row_by_row(conn: sqlite3.Connection) -> list[str]:
    ids = [row[0] for row in conn.execute("SELECT id FROM observations ORDER BY id")]
    return [
        conn.execute("SELECT payload FROM observations WHERE id = ?", (i,)).fetchone()[0]
        for i in ids
    ]


def test_an_unindexed_query_is_reported_as_a_scan(stored: sqlite3.Connection) -> None:
    costs = measure(
        stored,
        lambda: stored.execute(
            "SELECT id FROM observations WHERE payload LIKE '%Cursor%'"
        ).fetchall(),
    )

    assert [(scan.table, scan.statement) for scan in costs.full_scans] == [
        ("observations", "SELECT id FROM observations WHERE payload LIKE ?")
    ]


def test_an_indexed_range_is_not_a_scan(stored: sqlite3.Connection) -> None:
    costs = measure(
        stored,
        lambda: stored.execute(
            "SELECT id FROM observations WHERE source = 'aw-window'"
            " AND started_at >= '2026-01-05T09:00:00.000Z' AND started_at < '2026-01-05T10:00:00Z'"
        ).fetchall(),
    )

    assert costs.full_scans == ()
    assert costs.statements == 1


def test_an_added_per_row_query_raises_the_statement_count(stored: sqlite3.Connection) -> None:
    once = measure(stored, lambda: _read_apps(stored))
    per_row = measure(stored, lambda: _read_apps_row_by_row(stored))

    assert once.statements == 1
    assert per_row.statements == 4
    assert {text: cost.count for text, cost in per_row.by_statement.items()} == {
        "SELECT id FROM observations ORDER BY id": 1,
        "SELECT payload FROM observations WHERE id = ?": 3,
    }


def test_the_meter_gives_identical_counts_on_repeated_runs(stored: sqlite3.Connection) -> None:
    _read_apps_row_by_row(stored)
    runs = [measure(stored, lambda: _read_apps_row_by_row(stored)) for _ in range(3)]

    assert runs[0].vm_steps > 0
    assert runs[0] == runs[1] == runs[2]


def test_vm_steps_grow_with_the_rows_a_query_visits(stored: sqlite3.Connection) -> None:
    few = measure(stored, lambda: _read_apps(stored))
    stored.executemany(
        "INSERT INTO observations (source, source_id, started_at, ended_at, payload, ingested_at)"
        " VALUES ('aw-afk', ?, '2026-01-05T10:00:00Z', '2026-01-05T10:01:00Z', '{}', 'now')",
        [(str(n),) for n in range(100)],
    )
    many = measure(stored, lambda: _read_apps(stored))

    assert many.vm_steps > 10 * few.vm_steps


def test_pages_count_the_whole_database_and_each_table(stored: sqlite3.Connection) -> None:
    costs = measure(stored, lambda: None)

    assert costs.pages == stored.execute("PRAGMA page_count").fetchone()[0]
    assert costs.table_pages["observations"] >= 1
    assert sum(costs.table_pages.values()) <= costs.pages
