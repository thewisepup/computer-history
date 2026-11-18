"""The SQLite store: schema migrations and persistence.

Only this package knows SQL. Commands open the database with open_store,
which reports its state. Writers use insert_observations and the cursor
setters, rebuild-signals uses rebuild_signals, status uses the read queries.
"""

from computer_history.store.cursors import (
    get_cursor,
    init_cursor,
    set_cursor,
)
from computer_history.store.db import (
    BUSY_TIMEOUT_SECONDS,
    Migration,
    connect,
    load_migrations,
    migrate,
    schema_version,
    transaction,
)
from computer_history.store.observations import (
    Cursor,
    InsertResult,
    Observation,
    Signal,
    insert_observations,
)
from computer_history.store.opening import OpenedStore, Purpose, StoreState, open_store
from computer_history.store.paths import DB_ENV_VAR, default_db_path, resolve_db_path
from computer_history.store.signals import (
    Projector,
    RebuildAborted,
    RebuildResult,
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
    "Cursor",
    "Gap",
    "InsertResult",
    "Migration",
    "Observation",
    "OpenedStore",
    "Projector",
    "Purpose",
    "RebuildAborted",
    "RebuildResult",
    "Signal",
    "SourceSummary",
    "StoreState",
    "connect",
    "default_db_path",
    "find_gaps",
    "get_cursor",
    "init_cursor",
    "insert_observations",
    "load_migrations",
    "migrate",
    "open_store",
    "rebuild_signals",
    "resolve_db_path",
    "schema_version",
    "set_cursor",
    "source_summary",
    "table_counts",
    "to_utc",
    "transaction",
    "utc_iso",
]
