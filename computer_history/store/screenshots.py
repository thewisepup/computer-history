from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import NamedTuple

from computer_history.store.timefmt import to_utc, utc_iso

SCREENSHOT_STATUS_INDEX = "observations_screenshot_status"
# These expressions match the screenshot status index's columns exactly.
_FROM = "FROM observations WHERE source = 'screenshot'"
_STATUS = "json_extract(payload, '$.status')"
_IMAGE_BYTES = "json_extract(payload, '$.image_bytes')"


class StatusTotal(NamedTuple):
    count: int
    image_bytes: int


class NewestScreenshot(NamedTuple):
    at: datetime
    app_name: str | None
    image_path: str | None


def screenshot_totals(
    conn: sqlite3.Connection, *, until: datetime | str, since: datetime | str | None = None
) -> dict[str, StatusTotal]:
    """The stored screenshot records up to a time, from a time on if given, counted by status.

    Each count comes with the image bytes its records name, summed.
    """
    later, params = ("", ()) if since is None else (" AND started_at >= ?", (utc_iso(since),))
    rows = conn.execute(
        f"SELECT {_STATUS}, COUNT(*), SUM({_IMAGE_BYTES}) {_FROM} AND started_at <= ?{later}"
        f" GROUP BY {_STATUS}",
        (utc_iso(until), *params),
    )
    return {status: StatusTotal(count, summed or 0) for status, count, summed in rows}


def newest_screenshot(
    conn: sqlite3.Connection, status: str, *, until: datetime | str
) -> NewestScreenshot | None:
    """The time, app and image path of the newest stored screenshot record of a status by then."""
    newest = conn.execute(
        f"SELECT started_at, id {_FROM} AND {_STATUS} = ? AND started_at <= ?"
        " ORDER BY started_at DESC LIMIT 1",
        (status, utc_iso(until)),
    ).fetchone()
    if newest is None:
        return None
    app, path = conn.execute(
        "SELECT json_extract(payload, '$.app_name'), json_extract(payload, '$.image_path')"
        " FROM observations WHERE id = ?",
        (newest[1],),
    ).fetchone()
    return NewestScreenshot(to_utc(newest[0]), app, path)


def first_screenshot_at(
    conn: sqlite3.Connection, status: str, *, after: datetime | str | None = None
) -> datetime | None:
    """The time of the oldest stored screenshot record of a status, later than a time if given."""
    later, params = ("", ()) if after is None else (" AND started_at > ?", (utc_iso(after),))
    (first,) = conn.execute(
        f"SELECT MIN(started_at) {_FROM} AND {_STATUS} = ?{later}", (status, *params)
    ).fetchone()
    return None if first is None else to_utc(first)
