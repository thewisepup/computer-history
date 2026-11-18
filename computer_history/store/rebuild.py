"""Rebuild the disposable ``signals`` table from raw ``observations`` (DESIGN.md §3.2).

The store does not know any source's payload dialect, so the caller passes the
projector (for ActivityWatch: ``sources.project_signal``) and the version of the
mapping code it implements. ``observations`` is only read, never written.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from typing import NamedTuple

from computer_history.store.bookkeeping import get_mapping_version, set_mapping_version
from computer_history.store.db import transaction
from computer_history.store.writes import _INSERT_SIGNAL, Signal, _signal_params

log = logging.getLogger(__name__)

#: ``project(source, stored_payload_text) -> Signal | None``; ``None`` = no content (AFK).
Projector = Callable[[str, str], Signal | None]

DEFAULT_BATCH_SIZE = 1000
# Abort (and roll back) once more than this share of content observations fail to
# project: a "rebuild" that wipes signals and then skips most rows is a bug in
# the projector, not malformed data.
MAX_FAILURE_RATIO = 0.5
# Abort if the rebuild would leave fewer than this share of the signals it found,
# unless the caller allows it: catches a projector that wrongly returns None
# (no content) for content rows, which raises nothing and so skips nothing.
MIN_KEPT_RATIO = 0.5
# ...but only for stores with at least this many signals; tiny ones may shrink.
SHRINK_CHECK_MIN_SIGNALS = 50
# Log this many skipped observations individually, then only the total.
MAX_LOGGED_FAILURES = 20


class RebuildResult(NamedTuple):
    signals_before: int
    signals_after: int
    # Content observations that could not be projected (malformed payload): they
    # have no signal row now. ``failed_ids`` holds the first few of their ids.
    skipped: int
    failed_ids: tuple[int, ...]
    previous_mapping_version: int | None
    mapping_version: int


class RebuildAborted(RuntimeError):
    """The rebuild looked wrong and was rolled back; signals are unchanged.

    ``failed``/``failed_ids`` count and sample the observations that failed to
    project before the abort. ``shrink`` is true for the shrink check, which
    ``allow_shrink=True`` overrides.
    """

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
    mapping_version: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
    allow_shrink: bool = False,
) -> RebuildResult:
    """Wipe ``signals`` and re-project every observation with ``project``, atomically.

    One transaction: the wipe, every re-inserted row and the new
    ``signals_meta.mapping_version`` commit together, or (on any error, or a
    crash) none of it does and the old signals stay. Rows are built like
    :func:`insert_observations` builds them: ``source``/``started_at``/``ended_at``
    copied from the observation row as stored, ``observation_id`` as the key.

    ``project`` returning ``None`` means the source has no content (AFK): no row.
    If it raises for one observation (malformed payload), that observation is
    logged, skipped and counted, and the rebuild goes on. Two sanity checks raise
    :class:`RebuildAborted` and roll back instead:

    * more than :data:`MAX_FAILURE_RATIO` of the content observations fail. This
      is checked as the scan goes, against an upper bound on the content count
      (rows projected + failed + not yet scanned), so a projector that fails on
      every row stops after about half the table, not at the end;
    * the result keeps fewer than :data:`MIN_KEPT_RATIO` of the existing signals
      (stores with at least :data:`SHRINK_CHECK_MIN_SIGNALS`), unless
      ``allow_shrink``: a projector wrongly returning ``None`` raises nothing.

    Observations are streamed, never loaded all at once.

    **Blocks other writers while it runs.** The transaction takes SQLite's write
    lock (``BEGIN IMMEDIATE``) for the whole scan, so a concurrent ``ingest``
    waits up to the busy timeout and then fails with "database is locked";
    ``ingest --watch`` logs that and retries next cycle. Fine at M1 volumes. If
    rebuild time ever matters, the upgrade path is building into a shadow table
    outside the lock and swapping it in with one short transaction.

    Opens its own transaction, so it must not be called inside ``transaction()``.
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
        # Content observations number at most projected + failed + unscanned rows.
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
        previous = get_mapping_version(conn)
        before = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        # Stable for the whole scan: the write lock keeps other writers out.
        total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        conn.execute("DELETE FROM signals")
        rows = conn.execute(
            "SELECT id, source, started_at, ended_at, payload FROM observations ORDER BY id"
        )
        for observation_id, source, started_at, ended_at, payload in rows:
            scanned += 1
            try:
                signal = project(source, payload)
            except Exception as exc:  # malformed payload: skip it, never the whole rebuild
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
        check_failures(total)  # exact now: every row is scanned
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
        set_mapping_version(conn, mapping_version)
    return RebuildResult(
        signals_before=before,
        signals_after=projected,
        skipped=failed,
        failed_ids=tuple(failed_ids),
        previous_mapping_version=previous,
        mapping_version=int(mapping_version),
    )
