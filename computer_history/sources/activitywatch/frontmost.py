"""The app in front on a host, from aw-window: its stored spans and each bucket's newest event."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime
from typing import Any, NamedTuple

from computer_history.sources.activitywatch.client import AWApi
from computer_history.sources.activitywatch.discovery import WINDOW_SOURCE
from computer_history.sources.activitywatch.pull import MALFORMED_EVENT, event_times, newest_events
from computer_history.store import payload_values
from computer_history.text import clean_text

WINDOW_APP_PATH = "$.data.app"


class AppSpan(NamedTuple):
    start: datetime
    end: datetime
    app: str


def stored_app_spans(
    conn: sqlite3.Connection, start: datetime, end: datetime, *, hostname: str
) -> list[AppSpan]:
    """The stored spans of the host's window buckets touching the range, oldest first.

    Spans with no app are skipped.
    """
    return [
        AppSpan(row.started_at, row.ended_at, app)
        for row in payload_values(conn, WINDOW_SOURCE, start, end, (WINDOW_APP_PATH,))
        if on_host(row.source_id.rpartition("/")[0], hostname)
        and (app := clean_text(row.values[0])) is not None
    ]


def newest_app_spans(client: AWApi, buckets: Mapping[str, Any], *, hostname: str) -> list[AppSpan]:
    """The newest event of each of the host's listed window buckets, even one still growing."""
    spans = (
        _span(raw)
        for bucket_id, raw in newest_events(client, WINDOW_SOURCE, buckets)
        if on_host(bucket_id, hostname)
    )
    return [span for span in spans if span is not None]


def on_host(bucket_id: str, hostname: str) -> bool:
    """Whether a watcher on the host made the bucket, which ActivityWatch names watcher_host."""
    return bool(hostname) and bucket_id.endswith(f"_{hostname}")


def _span(raw: Any) -> AppSpan | None:
    try:
        app = clean_text(raw["data"]["app"])
        start, end = event_times(raw)
    except MALFORMED_EVENT:
        return None
    return None if app is None else AppSpan(start, end, app)
