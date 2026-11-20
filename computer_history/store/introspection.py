"""What SQLite reports about a database's work and size: query plans, pages and its build."""

from __future__ import annotations

import re
import sqlite3
from typing import NamedTuple

_SCAN = re.compile(r"SCAN (\w+)")


class SqliteBuild(NamedTuple):
    version: str
    compile_options: tuple[str, ...]


def scanned_tables(conn: sqlite3.Connection, sql: str) -> list[str]:
    """The schema tables a read statement's query plan visits row by row, in plan order."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
    tables.add("sqlite_master")
    plan = (_SCAN.match(row[3]) for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}"))
    return [match.group(1) for match in plan if match and match.group(1) in tables]


def page_counts(conn: sqlite3.Connection) -> tuple[int, dict[str, int]]:
    """The database's pages in all, and the pages of each table and index by name."""
    total = conn.execute("PRAGMA page_count").fetchone()[0]
    per_name = {
        name: pages
        for name, pages in conn.execute(
            "SELECT name, COUNT(*) FROM dbstat GROUP BY name ORDER BY name"
        )
    }
    return total, per_name


def sqlite_build(conn: sqlite3.Connection) -> SqliteBuild:
    """The SQLite library's version and compile options."""
    version = conn.execute("SELECT sqlite_version()").fetchone()[0]
    options = tuple(row[0] for row in conn.execute("PRAGMA compile_options"))
    return SqliteBuild(version, options)
