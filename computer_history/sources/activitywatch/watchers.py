from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from computer_history.sources.activitywatch.client import AWApi
from computer_history.sources.activitywatch.discovery import (
    AFK_SOURCE,
    WINDOW_SOURCE,
    discover_sources,
)
from computer_history.sources.activitywatch.frontmost import on_host
from computer_history.sources.activitywatch.pull import MALFORMED_EVENT, event_times, newest_events

WATCHED_SOURCES = (AFK_SOURCE, WINDOW_SOURCE)


def watcher_ends(
    client: AWApi, buckets: Mapping[str, Any], *, hostname: str
) -> dict[str, datetime | None]:
    """Where the newest event of each of the host's AFK and window buckets ends.

    A bucket with no usable event ends at None.
    """
    watched = {
        source.name: source.bucket_ids
        for source in discover_sources(client, buckets=buckets)
        if source.name in WATCHED_SOURCES
    }
    ends: dict[str, datetime | None] = {
        bucket_id: None
        for bucket_ids in watched.values()
        for bucket_id in bucket_ids
        if on_host(bucket_id, hostname)
    }
    for source in WATCHED_SOURCES:
        for bucket_id, raw in newest_events(client, source, buckets):
            if bucket_id in ends:
                try:
                    ends[bucket_id] = event_times(raw)[1]
                except MALFORMED_EVENT:
                    continue
    return ends
