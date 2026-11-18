"""The ActivityWatch ingest position: the UTC time a stream is settled up to."""

from __future__ import annotations

from datetime import datetime, timedelta

from computer_history.store import to_utc, utc_iso

RESUME_OVERLAP_SECONDS = 600


def position_at(settled_until: datetime) -> str:
    """The position of a stream whose events are all stored up to the given time."""
    return utc_iso(settled_until)


def resume_start(position: str) -> datetime:
    """Where the next poll starts reading: a little before the stored position."""
    return to_utc(position) - timedelta(seconds=RESUME_OVERLAP_SECONDS)
