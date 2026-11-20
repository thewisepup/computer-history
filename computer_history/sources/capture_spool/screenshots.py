from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import NamedTuple

from computer_history.sources.capture_spool.record import SCREENSHOT_SOURCE, SCREENSHOT_STATUSES
from computer_history.store import latest_payload_value, payload_totals, payload_values, to_utc
from computer_history.text import clean_text

STATUS_PATH = "$.status"
IMAGE_BYTES_PATH = "$.image_bytes"
KEPT_PATHS = (STATUS_PATH, "$.app_name", "$.image_path")
KEPT = "kept"
DUPLICATE = "duplicate"
NO_PERMISSION = "no-permission"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NO_RECORDS: Mapping[str, int] = MappingProxyType(dict.fromkeys(SCREENSHOT_STATUSES, 0))


class KeptScreenshot(NamedTuple):
    at: datetime
    app: str | None
    image_path: str | None


@dataclass(frozen=True)
class ScreenshotTally:
    """How many screenshot records of each status, and the bytes of the images they kept."""

    statuses: Mapping[str, int] = NO_RECORDS
    image_bytes: int = 0


@dataclass(frozen=True)
class ScreenshotHealth:
    """What status reports about screenshots, read from stored screenshot records only."""

    reported: bool
    last_kept: KeptScreenshot | None = None
    no_permission_since: datetime | None = None
    total: ScreenshotTally = ScreenshotTally()
    today: ScreenshotTally = ScreenshotTally()


def screenshot_health(
    conn: sqlite3.Connection, *, now: datetime, day_start: datetime | None = None
) -> ScreenshotHealth:
    """Report on the stored screenshot records up to now, and those since the day began."""
    now = to_utc(now)
    if latest_payload_value(conn, SCREENSHOT_SOURCE, STATUS_PATH, until=now) is None:
        return ScreenshotHealth(reported=False)
    if day_start is None:
        day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return ScreenshotHealth(
        reported=True,
        last_kept=_last_kept(conn, now),
        no_permission_since=_no_permission_since(conn, now),
        total=_tally(conn, EPOCH, now),
        today=_tally(conn, day_start, now),
    )


def _tally(conn: sqlite3.Connection, since: datetime, until: datetime) -> ScreenshotTally:
    totals = payload_totals(
        conn, SCREENSHOT_SOURCE, STATUS_PATH, IMAGE_BYTES_PATH, since=since, until=until
    )
    statuses = {s: totals[s].count if s in totals else 0 for s in SCREENSHOT_STATUSES}
    return ScreenshotTally(statuses, totals[KEPT].total if KEPT in totals else 0)


def _last_kept(conn: sqlite3.Connection, now: datetime) -> KeptScreenshot | None:
    found = latest_payload_value(conn, SCREENSHOT_SOURCE, STATUS_PATH, until=now, matching=KEPT)
    if found is None:
        return None
    rows = payload_values(conn, SCREENSHOT_SOURCE, found[0], found[0], KEPT_PATHS)
    _, app, path = [row.values for row in rows if row.values[0] == KEPT][-1]
    return KeptScreenshot(
        found[0],
        clean_text(app) if isinstance(app, str) else None,
        path if isinstance(path, str) else None,
    )


def _no_permission_since(conn: sqlite3.Connection, now: datetime) -> datetime | None:
    kept, duplicate, refused = (
        latest_payload_value(conn, SCREENSHOT_SOURCE, STATUS_PATH, until=now, matching=status)
        for status in (KEPT, DUPLICATE, NO_PERMISSION)
    )
    taken = max((found[0] for found in (kept, duplicate) if found is not None), default=EPOCH)
    if refused is None or refused[0] <= taken:
        return None
    rows = payload_values(conn, SCREENSHOT_SOURCE, taken, now, (STATUS_PATH,))
    return next(r.started_at for r in rows if r.started_at > taken and r.values[0] == NO_PERMISSION)
