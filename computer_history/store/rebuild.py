"""Rebuild the signals table from the stored observations.

The caller passes the projector function. Observations are only read, never
written.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from typing import NamedTuple

from computer_history.store.db import transaction
from computer_history.store.writes import _INSERT_SIGNAL, Signal, _signal_params

log = logging.getLogger(__name__)

Projector = Callable[[str, str], Signal | None]

DEFAULT_BATCH_SIZE = 1000
MAX_FAILURE_RATIO = 0.5
MIN_KEPT_RATIO = 0.5
SHRINK_CHECK_MIN_SIGNALS = 50
MAX_LOGGED_FAILURES = 20


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
    ) -> None:
        super().__init__(f"{reason}; rolled back, signals unchanged")
        self.failed = failed
        self.failed_ids = failed_ids
        self.shrink = shrink


def rebuild_signals(
    conn: sqlite3.Connection,
    project: Projector,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    allow_shrink: bool = False,
) -> RebuildResult:
    """Wipe the signals table and re-project every observation, atomically.

    On any error or crash nothing sticks and the old signals stay. An
    observation that fails to project is logged and skipped. The rebuild
    aborts if too many observations fail, or if the result would shrink far
    below the existing signals (pass allow_shrink to permit that).

    Blocks other writers while it runs. Opens its own transaction, so it must
    not be called inside transaction().
    """
    if conn.in_transaction:
        raise RuntimeError(
            "rebuild_signals opens its own transaction; it must not be called inside transaction()"
        )
    if batch_size < 1:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    projected = failed = scanned = 0
    failed_ids: list[int] = []
    batch: list[tuple[int | str | None, ...]] = []

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
        before = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        conn.execute("DELETE FROM signals")
        rows = conn.execute(
            "SELECT id, source, started_at, ended_at, payload FROM observations ORDER BY id"
        )
        for observation_id, source, started_at, ended_at, payload in rows:
            scanned += 1
            try:
                signal = project(source, payload)
            except Exception as exc:
                failed += 1
                if len(failed_ids) < MAX_LOGGED_FAILURES:
                    failed_ids.append(observation_id)
                    log.warning(
                        "rebuild-signals: skipping observation %d (%s): cannot project its"
                        " payload: %r",
                        observation_id,
                        source,
                        exc,
                    )
                check_failures(total)
                continue
            if signal is None:
                continue
            projected += 1
            batch.append(_signal_params(observation_id, source, started_at, ended_at, signal))
            if len(batch) >= batch_size:
                conn.executemany(_INSERT_SIGNAL, batch)
                batch.clear()
        if batch:
            conn.executemany(_INSERT_SIGNAL, batch)
        if failed > MAX_LOGGED_FAILURES:
            log.warning(
                "rebuild-signals: %d more observations skipped (not logged individually)",
                failed - MAX_LOGGED_FAILURES,
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
