"""SQLite store: schema migrations and persistence (Milestone 1).

Only this package knows SQL. Writers use :func:`insert_observations` and the
bookkeeping setters; ``status`` uses the queries in :mod:`.reads`.
"""

from computer_history.store.bookkeeping import (
    get_cursor,
    get_mapping_version,
    set_cursor,
    set_mapping_version,
)
from computer_history.store.db import (
    BUSY_TIMEOUT_SECONDS,
    Migration,
    connect,
    connect_readonly,
    load_migrations,
    migrate,
    schema_version,
    transaction,
)
from computer_history.store.paths import DB_ENV_VAR, default_db_path, resolve_db_path
from computer_history.store.reads import (
    Gap,
    SourceSummary,
    find_gaps,
    source_summary,
    table_counts,
)
from computer_history.store.timefmt import to_utc, utc_iso
from computer_history.store.writes import (
    Cursor,
    InsertResult,
    Observation,
    Signal,
    insert_observations,
)

__all__ = [
    "BUSY_TIMEOUT_SECONDS",
    "DB_ENV_VAR",
    "Cursor",
    "Gap",
    "InsertResult",
    "Migration",
    "Observation",
    "Signal",
    "SourceSummary",
    "connect",
    "connect_readonly",
    "default_db_path",
    "find_gaps",
    "get_cursor",
    "get_mapping_version",
    "insert_observations",
    "load_migrations",
    "migrate",
    "resolve_db_path",
    "schema_version",
    "set_cursor",
    "set_mapping_version",
    "source_summary",
    "table_counts",
    "to_utc",
    "transaction",
    "utc_iso",
]
