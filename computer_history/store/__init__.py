"""The SQLite store: schema migrations and persistence.

Only this package knows SQL. Commands open the database with open_store,
which reports its state. Ingest writes through insert_observations, the only
way a source's progress moves. It and rebuild_signals both turn a stored
payload into its signal with the projector the caller passes, and status and
backfill use the read queries.
"""

from computer_history.store.db import (
    BUSY_TIMEOUT_SECONDS,
    Migration,
    connect,
    load_migrations,
    migrate,
    schema_version,
    transaction,
)
from computer_history.store.observations import InsertResult, Observation, insert_observations
from computer_history.store.opening import OpenedStore, Purpose, StoreState, open_store
from computer_history.store.paths import DB_ENV_VAR, default_db_path, resolve_db_path
from computer_history.store.progress import Progress, ProgressUpdate, get_progress
from computer_history.store.signals import (
    Projector,
    RebuildAborted,
    RebuildResult,
    Signal,
    UnclaimedSource,
    rebuild_signals,
)
from computer_history.store.status import (
    Gap,
    SourceSummary,
    find_gaps,
    source_summary,
    table_counts,
)
from computer_history.store.timefmt import to_utc, utc_iso

__all__ = [
    "BUSY_TIMEOUT_SECONDS",
    "DB_ENV_VAR",
    "Gap",
    "InsertResult",
    "Migration",
    "Observation",
    "OpenedStore",
    "Progress",
    "ProgressUpdate",
    "Projector",
    "Purpose",
    "RebuildAborted",
    "RebuildResult",
    "Signal",
    "SourceSummary",
    "StoreState",
    "UnclaimedSource",
    "connect",
    "default_db_path",
    "find_gaps",
    "get_progress",
    "insert_observations",
    "load_migrations",
    "migrate",
    "open_store",
    "rebuild_signals",
    "resolve_db_path",
    "schema_version",
    "source_summary",
    "table_counts",
    "to_utc",
    "transaction",
    "utc_iso",
]
