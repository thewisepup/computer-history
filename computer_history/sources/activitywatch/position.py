"""The ActivityWatch ingest position: the UTC time a source is settled up to."""

from __future__ import annotations

from datetime import datetime, timedelta

from computer_history.store import ProgressUpdate, to_utc, utc_iso

RESUME_OVERLAP_SECONDS = 600


def progress_at(source: str, frontier: datetime, *, only_if_none: bool = False) -> ProgressUpdate:
    """The progress update for a source whose events are all stored up to the frontier."""
    return ProgressUpdate(
        source, utc_iso(frontier), settled_until=frontier, only_if_none=only_if_none
    )


def resume_start(position: str) -> datetime:
    """Where the next poll starts reading: a little before the stored position."""
    return to_utc(position) - timedelta(seconds=RESUME_OVERLAP_SECONDS)
