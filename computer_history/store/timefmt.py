"""The store's one canonical timestamp format.

Every stored timestamp is UTC ISO-8601 with microseconds, so timestamps
compare correctly as plain text. Every writer puts timestamps through
utc_iso() before they reach SQLite.
"""

from __future__ import annotations

from datetime import UTC, datetime

CANONICAL_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"  # + 'Z'; microseconds, always UTC


def utc_iso(value: datetime | str) -> str:
    """Canonical form: YYYY-MM-DDTHH:MM:SS.ffffffZ.

    Accepts a timezone-aware datetime or any ISO-8601 string with an offset.
    A timestamp without a timezone is rejected, never guessed.
    """
    return to_utc(value).strftime(CANONICAL_FORMAT) + "Z"


def to_utc(value: datetime | str) -> datetime:
    """Parse or convert a timestamp into an aware UTC datetime."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware: {value!r}")
    return value.astimezone(UTC)
