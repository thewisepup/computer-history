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
from computer_history.sources.activitywatch.pull import MALFORMED_EVENT, event_times
from computer_history.sources.contract import SourceUnavailable

WATCHED_SOURCES = (AFK_SOURCE, WINDOW_SOURCE)


def watcher_ends(
    client: AWApi, buckets: Mapping[str, Any], *, hostname: str
) -> dict[str, datetime | None]:
    """Where each of this host's AFK and window sources last advanced, by its newest bucket."""
    ends: dict[str, datetime | None] = {}
    for source in discover_sources(buckets):
        on_this_host = [bucket for bucket in source.bucket_ids if on_host(bucket, hostname)]
        if source.name not in WATCHED_SOURCES or not on_this_host:
            continue
        found = [end for bucket in on_this_host if (end := _newest_end(client, bucket))]
        ends[source.name] = max(found, default=None)
    return ends


def _newest_end(client: AWApi, bucket_id: str) -> datetime | None:
    try:
        newest = client.get_events(bucket_id, limit=1)
    except SourceUnavailable:
        return None
    try:
        return event_times(newest[0])[1] if newest else None
    except MALFORMED_EVENT:
        return None
