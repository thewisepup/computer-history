"""Pull settled ActivityWatch events into the store.

    ActivityWatch HTTP API
          |
      client.py      the HTTP calls, nothing else
          |
      discovery.py   buckets -> sources (aw-window, aw-afk, aw-web)
          |
      pull.py        fetch one bucket's events, keep the settled ones
          |
      normalize.py   raw payload -> signal (app, domain, url, title)
          |
      ingest.py      the orchestrator: batch + cursor, one atomic write
          |
      store/ (SQLite)

An event that may still be growing is held back for a later poll: delayed,
never lost. Every event starting before a source's cursor is stored.
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
    CURSOR_OVERLAP_SECONDS,
    IngestOutcome,
    ingest_all,
    ingest_source,
)
from computer_history.sources.activitywatch.normalize import project_signal
from computer_history.sources.activitywatch.pull import (
    STABILITY_MARGIN_SECONDS,
    BucketPull,
    pull_bucket,
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
    "CURSOR_OVERLAP_SECONDS",
    "DEFAULT_AW_URL",
    "MAX_TEXT_LENGTH",
    "MAX_URL_LENGTH",
    "STABILITY_MARGIN_SECONDS",
    "WEB_SOURCE",
    "WINDOW_SOURCE",
    "AWApi",
    "AWClient",
    "AWError",
    "AWSource",
    "BucketPull",
    "IngestOutcome",
    "clean_text",
    "clean_url",
    "discover_sources",
    "extract_domain",
    "ingest_all",
    "ingest_source",
    "project_signal",
    "pull_bucket",
]
