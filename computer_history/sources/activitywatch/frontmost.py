"""The app in front, from aw-window: its stored spans and each window bucket's newest event."""

from __future__ import annotations

import sqlite3
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
    conn: sqlite3.Connection, start: datetime | str, end: datetime | str
) -> list[AppSpan]:
    """The stored aw-window spans touching the range, oldest first, skipping those with no app."""
    return [
        AppSpan(row.started_at, row.ended_at, app)
        for row in payload_values(conn, WINDOW_SOURCE, start, end, (WINDOW_APP_PATH,))
        if (app := _app(row.values[0])) is not None
    ]


def newest_app_spans(client: AWApi) -> list[AppSpan]:
    """The newest event of every window bucket, including one still growing and not yet stored."""
    spans = (_span(raw) for raw in newest_events(client, WINDOW_SOURCE))
    return [span for span in spans if span is not None]


def _span(raw: Any) -> AppSpan | None:
    try:
        app = _app(raw["data"]["app"])
        start, end = event_times(raw)
    except MALFORMED_EVENT:
        return None
    return None if app is None else AppSpan(start, end, app)


def _app(value: Any) -> str | None:
    return clean_text(value) if isinstance(value, str) else None
