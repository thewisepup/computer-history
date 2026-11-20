"""The cost meter: how much SQLite work one operation does on a connection, counted exactly."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import NamedTuple

from computer_history.store import page_counts, scanned_tables

_LITERAL = re.compile(r"X'[0-9A-Fa-f]*'|'(?:[^']|'')*'|\b\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\b|\bNULL\b")
_PLACEHOLDER_LIST = re.compile(r"\?(?:\s*,\s*\?)+")
_SPACE = re.compile(r"\s+")
_READ = re.compile(r"(?:SELECT|WITH)\b", re.I)


class StatementCost(NamedTuple):
    count: int
    vm_steps: int


class Scan(NamedTuple):
    table: str
    statement: str


@dataclass(frozen=True)
class Costs:
    """What one measured run did: statements by text, VM steps, full scans and database pages.

    Each statement is charged the VM steps run from its start until the next statement starts.
    """

    statements: int
    vm_steps: int
    full_scans: tuple[Scan, ...]
    pages: int
    table_pages: Mapping[str, int]
    by_statement: Mapping[str, StatementCost]


def statement_text(sql: str) -> str:
    """The statement with its literal values written as placeholders, on one line."""
    text = _PLACEHOLDER_LIST.sub("?, ...", _LITERAL.sub("?", sql))
    return _SPACE.sub(" ", text).strip().rstrip(";").rstrip()


def measure(conn: sqlite3.Connection, action: Callable[[], object], *, pages: bool = True) -> Costs:
    """Run the action once, counting every statement and VM instruction it runs on the connection.

    Without pages, the database's pages are left at zero.
    """
    counts: dict[str, int] = {}
    steps: dict[str, int] = {}
    examples: dict[str, str] = {}
    current = ["(before any statement)"]

    def traced(sql: str) -> None:
        text = statement_text(sql)
        counts[text] = counts.get(text, 0) + 1
        examples.setdefault(text, sql)
        current[0] = text

    def stepped() -> int:
        steps[current[0]] = steps.get(current[0], 0) + 1
        return 0

    conn.set_trace_callback(traced)
    conn.set_progress_handler(stepped, 1)
    try:
        action()
    finally:
        conn.set_progress_handler(None, 1)
        conn.set_trace_callback(None)
    scans = tuple(
        Scan(table, text)
        for text, sql in sorted(examples.items())
        if _READ.match(sql.lstrip())
        for table in scanned_tables(conn, sql)
    )
    total, table_pages = page_counts(conn) if pages else (0, {})
    by_statement = {
        text: StatementCost(counts.get(text, 0), steps.get(text, 0))
        for text in sorted(counts.keys() | steps.keys())
    }
    return Costs(
        statements=sum(counts.values()),
        vm_steps=sum(steps.values()),
        full_scans=scans,
        pages=total,
        table_pages=table_pages,
        by_statement=by_statement,
    )
