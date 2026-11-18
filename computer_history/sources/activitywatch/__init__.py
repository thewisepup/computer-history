"""Pull settled ActivityWatch events into the store.

    ActivityWatch HTTP API
          |
      client.py      the HTTP calls, nothing else
          |
      discovery.py   buckets -> sources (aw-window, aw-afk, aw-web)
          |
      pull.py        fetch each bucket's events, keep the settled ones
          |          (a source's frontier is the earliest bucket frontier)
      normalize.py   raw payload -> signal (app, domain, url, title)
          |
      ingest.py      the orchestrator: batch + progress, one atomic write
          |          (position.py: progress is a UTC time, rewound on resume)
      store/ (SQLite)

An event that may still be growing is held back for a later poll: delayed,
never lost. Every event starting before a source's settled-until time is stored.
"""

from computer_history.sources.activitywatch.client import (
    DEFAULT_AW_URL,
    AWApi,
    AWClient,
    AWError,
)
from computer_history.sources.activitywatch.discovery import (
    AFK_SOURCE,
    WEB_SOURCE,
    WINDOW_SOURCE,
    AWSource,
    discover_sources,
)
from computer_history.sources.activitywatch.ingest import (
    IngestOutcome,
    ingest_all,
    ingest_source,
    outcome_of,
)
from computer_history.sources.activitywatch.normalize import project_signal
from computer_history.sources.activitywatch.position import (
    RESUME_OVERLAP_SECONDS,
    progress_at,
    resume_start,
)
from computer_history.sources.activitywatch.pull import (
    STABILITY_MARGIN_SECONDS,
    BucketPull,
    SourcePull,
    pull_bucket,
    pull_source,
)
from computer_history.text import (
    MAX_TEXT_LENGTH,
    MAX_URL_LENGTH,
    clean_text,
    clean_url,
    extract_domain,
)

__all__ = [
    "AFK_SOURCE",
    "DEFAULT_AW_URL",
    "MAX_TEXT_LENGTH",
    "MAX_URL_LENGTH",
    "RESUME_OVERLAP_SECONDS",
    "STABILITY_MARGIN_SECONDS",
    "WEB_SOURCE",
    "WINDOW_SOURCE",
    "AWApi",
    "AWClient",
    "AWError",
    "AWSource",
    "BucketPull",
    "IngestOutcome",
    "SourcePull",
    "clean_text",
    "clean_url",
    "discover_sources",
    "extract_domain",
    "ingest_all",
    "ingest_source",
    "outcome_of",
    "progress_at",
    "project_signal",
    "pull_bucket",
    "pull_source",
    "resume_start",
]
