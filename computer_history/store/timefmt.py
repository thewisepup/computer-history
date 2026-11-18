"""The store's one canonical timestamp format.

DESIGN.md §3 requires all stored timestamps to be UTC ISO-8601 at uniform
precision: ``block_evidence_v`` and the window/block math compare timestamps
as TEXT, so two spellings of the same instant ('…T10:00:00Z' vs
'…T10:00:00.000000Z') would sort as different moments. Every writer must put
timestamps through :func:`utc_iso` before they reach SQLite.
"""

from __future__ import annotations

from datetime import datetime, timezone

CANONICAL_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"  # + 'Z'; microseconds, always UTC


def utc_iso(value: datetime | str) -> str:
    """Canonical form: ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` (UTC, microseconds).

    Accepts a timezone-aware datetime or any ISO-8601 string with an offset
    ('Z' included). Naive values are rejected: per the design, a timestamp
    without a timezone is an input error, never assumed local or UTC.
    """
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware: {value!r}")
    return value.astimezone(timezone.utc).strftime(CANONICAL_FORMAT) + "Z"
