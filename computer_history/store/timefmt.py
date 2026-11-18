"""One timestamp format for everything in the database.

Every stored timestamp is UTC ISO-8601 with microseconds, so timestamps can
be compared as plain text.
"""

from __future__ import annotations

from datetime import UTC, datetime

CANONICAL_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def utc_iso(value: datetime | str) -> str:
    """Format a timestamp as YYYY-MM-DDTHH:MM:SS.ffffffZ.

    Accepts a datetime or an ISO-8601 string. Timestamps without a timezone
    are rejected.
    """
    return to_utc(value).strftime(CANONICAL_FORMAT) + "Z"


def to_utc(value: datetime | str) -> datetime:
    """Convert a timestamp into a UTC datetime."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware: {value!r}")
    return value.astimezone(UTC)
