"""What SQLite reports about a database's work and size: query plans, pages and its build."""

from __future__ import annotations

import re
import sqlite3
from typing import NamedTuple

_SCAN = re.compile(r"SCAN (?:TABLE )?(\w+)")
_NAMED = re.compile(r'\b(?:FROM|JOIN)\s+"?(\w+)"?(?:\s+(?:AS\s+)?"?(\w+)"?)?', re.I)
_NOT_ALIASES = frozenset(
    "CROSS EXCEPT FULL GROUP HAVING INDEXED INNER INTERSECT JOIN LEFT LIMIT NATURAL NOT ON"
    " ORDER OUTER RIGHT UNION USING WHERE WINDOW".split()
)


class DbstatUnavailable(RuntimeError):
    """This SQLite was built without the dbstat table, so pages per table cannot be counted."""


class SqliteBuild(NamedTuple):
    version: str
    compile_options: tuple[str, ...]


def scanned_tables(conn: sqlite3.Connection, sql: str) -> list[str]:
    """The schema tables a read statement's query plan visits row by row, in plan order.

    A table read under an alias counts as that table, and placeholders left in the text bind null.
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
    tables.add("sqlite_master")
    names = {table: table for table in tables}
    for table, alias in _NAMED.findall(sql):
        if table in tables and alias and alias.upper() not in _NOT_ALIASES:
            names.setdefault(alias, table)
    try:
        plan = conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    except sqlite3.ProgrammingError:
        plan = conn.execute(f"EXPLAIN QUERY PLAN {sql}", [None] * sql.count("?")).fetchall()
    found = (_SCAN.match(row[3]) for row in plan)
    return [names[match.group(1)] for match in found if match and match.group(1) in names]


def page_counts(conn: sqlite3.Connection) -> tuple[int, dict[str, int]]:
    """The database's pages in all, and the pages of each table and index by name."""
    total = conn.execute("PRAGMA page_count").fetchone()[0]
    try:
        rows = conn.execute("SELECT name, COUNT(*) FROM dbstat GROUP BY name ORDER BY name")
    except sqlite3.OperationalError as exc:
        raise DbstatUnavailable(f"SQLite {sqlite3.sqlite_version} has no dbstat table") from exc
    return total, dict(rows.fetchall())


def sqlite_build(conn: sqlite3.Connection) -> SqliteBuild:
    """The SQLite library's version and compile options."""
    version = conn.execute("SELECT sqlite_version()").fetchone()[0]
    options = tuple(row[0] for row in conn.execute("PRAGMA compile_options"))
    return SqliteBuild(version, options)
