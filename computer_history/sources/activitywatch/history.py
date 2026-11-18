"""What ActivityWatch can tell about a stream's existing history, for backfill planning."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from computer_history.sources.activitywatch.client import AWApi
from computer_history.sources.activitywatch.discovery import AWSource
from computer_history.store import to_utc

log = logging.getLogger(__name__)

_PROBE_GUARD = timedelta(microseconds=1)


def history_floor(buckets: Mapping[str, Any], source: AWSource) -> datetime | None:
    """Local midnight on or before the earliest bucket creation time, if any."""
    created = []
    for bucket_id in source.bucket_ids:
        meta = buckets.get(bucket_id)
        value = meta.get("created") if isinstance(meta, Mapping) else None
        try:
            created.append(to_utc(value))
        except (TypeError, ValueError, AttributeError):
            log.warning("bucket %s has no usable 'created' time (%r)", bucket_id, value)
    if not created:
        return None
    local = min(created).astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def history_before(
    client: AWApi, source: AWSource, start: datetime
) -> tuple[tuple[str, datetime | None], ...]:
    """Each bucket with an event beginning before the start, and when the newest one began."""
    earlier = []
    for bucket_id in source.bucket_ids:
        found, began = _event_before(client, bucket_id, start)
        if found:
            earlier.append((bucket_id, began))
    return tuple(earlier)


def _event_before(client: AWApi, bucket_id: str, start: datetime) -> tuple[bool, datetime | None]:
    """Whether the bucket has an event beginning before the start, and when it began.

    An event whose timestamp cannot be read still counts as earlier history.
    """
    for raw in client.get_events(bucket_id, end=start - _PROBE_GUARD, limit=1):
        try:
            began = to_utc(raw["timestamp"])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            log.warning(
                "malformed ActivityWatch event in %s before %s: %s; treating it as"
                " history the backfill does not cover",
                bucket_id,
                start.isoformat(),
                exc,
            )
            return True, None
        if began < start:
            return True, began
    return False, None
