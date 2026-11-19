"""Attended time from aw-afk: the stored AFK spans and each AFK bucket's newest event."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, NamedTuple

from computer_history.sources.activitywatch.client import AWApi
from computer_history.sources.activitywatch.discovery import AFK_SOURCE, discover_sources
from computer_history.sources.activitywatch.pull import MALFORMED_EVENT, event_times
from computer_history.store import payload_values

AFK_STATUS_PATH = "$.data.status"
AFK_STATUSES = {"afk": True, "not-afk": False}


class AfkSpan(NamedTuple):
    start: datetime
    end: datetime
    afk: bool


def stored_afk_spans(
    conn: sqlite3.Connection, start: datetime | str, end: datetime | str
) -> list[AfkSpan]:
    """The stored aw-afk spans touching the range, oldest first, skipping unknown statuses."""
    return [
        AfkSpan(row.started_at, row.ended_at, AFK_STATUSES[row.values[0]])
        for row in payload_values(conn, AFK_SOURCE, start, end, (AFK_STATUS_PATH,))
        if isinstance(row.values[0], str) and row.values[0] in AFK_STATUSES
    ]


def newest_afk_spans(client: AWApi) -> list[AfkSpan]:
    """The newest event of every AFK bucket, including one still growing and not yet stored."""
    spans = []
    for source in discover_sources(client):
        if source.name != AFK_SOURCE:
            continue
        for bucket_id in source.bucket_ids:
            for raw in client.get_events(bucket_id, limit=1):
                span = _span(raw)
                if span is not None:
                    spans.append(span)
    return spans


def _span(raw: Any) -> AfkSpan | None:
    try:
        status = raw["data"]["status"]
        start, end = event_times(raw)
    except MALFORMED_EVENT:
        return None
    if not isinstance(status, str) or status not in AFK_STATUSES:
        return None
    return AfkSpan(start, end, AFK_STATUSES[status])
