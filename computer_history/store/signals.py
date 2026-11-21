"""The signals table: its row shape, its writes, and the rebuild from stored observations.

Signals come from a projector the caller passes. Observations are only read, never written.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from typing import NamedTuple

from computer_history.store.db import transaction

log = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 1000
MAX_FAILURE_RATIO = 0.5
MIN_KEPT_RATIO = 0.5
SHRINK_CHECK_MIN_SIGNALS = 50
MAX_LOGGED_FAILURES = 20
PROGRESS_RECORDS = 5
MIN_PROGRESS_STEP = 10_000


@dataclass(frozen=True)
class Signal:
    """One observation's normalized, queryable fields. extras is a JSON string."""

    app: str | None = None
    domain: str | None = None
    url: str | None = None
    title: str | None = None
    text: str | None = None
    extras: str | None = None


Projector = Callable[[str, str], Signal | None]


class UnclaimedSource(LookupError):
    """No source adapter projects observations from this source."""

    def __init__(self, source: str) -> None:
        super().__init__(f"no source adapter projects observations from {source!r}")
        self.source = source


_INSERT_SIGNAL = """
INSERT INTO signals
  (observation_id, source, started_at, ended_at, app, domain, url, title, text, extras)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

SignalRow = tuple[int, str, str, str, Signal]


def write_signals(conn: sqlite3.Connection, rows: Iterable[SignalRow]) -> None:
    """Insert one signal row per (observation id, source, started_at, ended_at, signal)."""
    conn.executemany(
        _INSERT_SIGNAL,
        (
            (*keys, signal.app, signal.domain, signal.url, signal.title, signal.text, signal.extras)
            for *keys, signal in rows
        ),
    )


class RebuildResult(NamedTuple):
    signals_before: int
    signals_after: int
    skipped: int
    failed_ids: tuple[int, ...]


class RebuildAborted(RuntimeError):
    """The rebuild looked wrong and was rolled back. Signals are unchanged."""

    def __init__(
        self,
        reason: str,
        *,
        failed: int = 0,
        failed_ids: tuple[int, ...] = (),
        shrink: bool = False,
        unclaimed: str | None = None,
    ) -> None:
        super().__init__(f"{reason}; rolled back, signals unchanged")
        self.failed = failed
        self.failed_ids = failed_ids
        self.shrink = shrink
        self.unclaimed = unclaimed


def rebuild_signals(
    conn: sqlite3.Connection,
    project: Projector,
    *,
    claimed: Collection[str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    allow_shrink: bool = False,
) -> RebuildResult:
    """Wipe the signals table and re-project every observation, atomically.

    It rolls back if the result looks wrong.
    """
    if conn.in_transaction:
        raise RuntimeError(
            "rebuild_signals opens its own transaction; it must not be called inside transaction()"
        )
    if batch_size < 1:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    projected = failed = scanned = 0
    failed_ids: list[int] = []
    batch: list[SignalRow] = []

    def check_failures(total: int) -> None:
        bound = projected + failed + (total - scanned)
        if failed > bound * MAX_FAILURE_RATIO:
            raise RebuildAborted(
                f"too many malformed payloads: {failed:,} observations failed to project,"
                f" more than {MAX_FAILURE_RATIO:.0%} of the at most {bound:,} content"
                " observations",
                failed=failed,
                failed_ids=tuple(failed_ids),
            )

    with transaction(conn):
        if claimed is not None:
            _refuse_unclaimed(conn, claimed)
        before = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        conn.execute("DELETE FROM signals")
        step = max(MIN_PROGRESS_STEP, math.ceil(total / PROGRESS_RECORDS))
        rows = conn.execute(
            "SELECT id, source, started_at, ended_at, payload FROM observations ORDER BY id"
        )
        for observation_id, source, started_at, ended_at, payload in rows:
            scanned += 1
            if scanned % step == 0:
                log.info(
                    "rebuild progress",
                    extra={"scanned": scanned, "observations": total, "projected": projected},
                )
            try:
                signal = project(source, payload)
            except UnclaimedSource as exc:
                raise _unclaimed(conn, exc.source) from exc
            except Exception as exc:
                failed += 1
                if len(failed_ids) < MAX_LOGGED_FAILURES:
                    failed_ids.append(observation_id)
                    log.warning(
                        "observation skipped: its payload cannot be projected",
                        extra={
                            "observation_id": observation_id,
                            "source": source,
                            "error": type(exc).__name__,
                        },
                    )
                    log.debug(
                        "projection error",
                        extra={"observation_id": observation_id, "error": repr(exc)},
                    )
                check_failures(total)
                continue
            if signal is None:
                continue
            projected += 1
            batch.append((observation_id, source, started_at, ended_at, signal))
            if len(batch) >= batch_size:
                write_signals(conn, batch)
                batch.clear()
        if batch:
            write_signals(conn, batch)
        if failed > MAX_LOGGED_FAILURES:
            log.warning(
                "more observations skipped, not logged one by one",
                extra={"skipped": failed - MAX_LOGGED_FAILURES},
            )
        check_failures(total)
        if (
            not allow_shrink
            and before >= SHRINK_CHECK_MIN_SIGNALS
            and projected < before * MIN_KEPT_RATIO
        ):
            raise RebuildAborted(
                f"signals would shrink from {before:,} to {projected:,} rows (below"
                f" {MIN_KEPT_RATIO:.0%}), which looks like a projector bug",
                failed=failed,
                failed_ids=tuple(failed_ids),
                shrink=True,
            )
    return RebuildResult(
        signals_before=before,
        signals_after=projected,
        skipped=failed,
        failed_ids=tuple(failed_ids),
    )


def _refuse_unclaimed(conn: sqlite3.Connection, claimed: Collection[str]) -> None:
    for (source,) in conn.execute("SELECT DISTINCT source FROM observations ORDER BY source"):
        if source not in claimed:
            raise _unclaimed(conn, source) from UnclaimedSource(source)


def _unclaimed(conn: sqlite3.Connection, source: str) -> RebuildAborted:
    count, first_id = conn.execute(
        "SELECT COUNT(*), MIN(id) FROM observations WHERE source = ?", (source,)
    ).fetchone()
    plural = "" if count == 1 else "s"
    return RebuildAborted(
        f"no source adapter projects {source!r}, the source of {count:,} stored"
        f" observation{plural} (first id: {first_id})",
        unclaimed=source,
    )
