from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import NamedTuple

from computer_history.sources.capture_spool.record import (
    DUPLICATE_STATUS,
    KEPT_STATUS,
    NO_PERMISSION_STATUS,
    SCREENSHOT_STATUSES,
)
from computer_history.store import (
    first_screenshot_at,
    newest_screenshot,
    screenshot_totals,
    to_utc,
)
from computer_history.text import clean_text_or_none

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


def screenshot_health(conn: sqlite3.Connection, *, day_start: datetime) -> ScreenshotHealth:
    """Report on every stored screenshot record, and on those since the day began."""
    total = _tally(conn)
    if not any(total.statuses.values()):
        return ScreenshotHealth(reported=False)
    kept = newest_screenshot(conn, KEPT_STATUS)
    last_kept = None
    if kept is not None:
        app, image_path = clean_text_or_none(kept.app_name), clean_text_or_none(kept.image_path)
        last_kept = KeptScreenshot(kept.at, app, image_path)
    return ScreenshotHealth(
        reported=True,
        last_kept=last_kept,
        no_permission_since=_no_permission_since(conn),
        total=total,
        today=_tally(conn, since=to_utc(day_start)),
    )


def _tally(conn: sqlite3.Connection, since: datetime | None = None) -> ScreenshotTally:
    totals = screenshot_totals(conn, since=since)
    statuses = {s: totals[s].count if s in totals else 0 for s in SCREENSHOT_STATUSES}
    kept = totals.get(KEPT_STATUS)
    return ScreenshotTally(statuses, 0 if kept is None else kept.image_bytes)


def _no_permission_since(conn: sqlite3.Connection) -> datetime | None:
    kept, duplicate, refused = (
        newest_screenshot(conn, status)
        for status in (KEPT_STATUS, DUPLICATE_STATUS, NO_PERMISSION_STATUS)
    )
    taken = max((found.at for found in (kept, duplicate) if found is not None), default=None)
    if refused is None or (taken is not None and refused.at <= taken):
        return None
    return first_screenshot_at(conn, NO_PERMISSION_STATUS, after=taken)

