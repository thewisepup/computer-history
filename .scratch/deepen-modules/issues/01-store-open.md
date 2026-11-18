# 01 — Open the store by purpose

Type: task
Status: resolved
Blocked by: none

## Problem

Every command carries its own copy of the store lifecycle rules:
- `ingest` → `cli/db.open_store` → `connect` (creates + migrates; catches only
  `OperationalError`).
- `rebuild-signals` checks `db_path.exists()` itself so it won't create a DB.
- `status` checks `exists()`, opens `connect_readonly`, and compares
  `schema_version` with `load_migrations()[-1].version` itself.
- `backfill._read_cursors` checks `exists()`, opens read-only, treats
  `schema_version < 1` as "no cursors", so it reads an outdated schema.

Live bug: older code on a newer-schema DB → `migrate` raises `RuntimeError`,
`open_store` catches only `OperationalError` → `ingest`/`rebuild-signals`
crash with a traceback. Tests reach "busy" by monkeypatching `cli_db.connect`.

## Task

Add one store entry point that opens the database for a stated purpose
(read: never creates, never migrates; write: creates and migrates) and
reports a state instead of leaving callers to interpret versions and
exceptions. States at least: missing, outdated, newer than this code, busy,
ready. Rules:
- No command ever reads or writes a schema it doesn't match: reading an
  outdated DB is refused with a state (status prints "ingest will migrate"),
  a newer DB is refused for every purpose with a clear "upgrade" message.
- Write purpose on a missing DB creates it; write on a newer DB → newer state,
  never a traceback; lock contention → busy.
- All four commands use it. The CLI only maps a state to a message + exit
  code (one shared message mapper is fine). `cli/db.py` and
  `_read_cursors`' version logic go away, or shrink to pure message mapping.
- Decide whether `rebuild-signals` uses read-then-write or write-but-refuse-
  missing; it must still refuse to create a DB.
- `backfill`: dry run must not create or migrate; a real run may open for
  write first and read cursors from that connection.

## Acceptance

- Store tests create real temp SQLite files in each state (missing, outdated
  via a partial migration list or a lowered user_version, newer via a raised
  user_version, locked via a second connection holding BEGIN IMMEDIATE,
  ready) and assert the reported state through the one entry point.
- CLI tests: newer-schema DB → every command prints the upgrade message and
  exits non-zero with no traceback. Remove monkeypatching of `cli_db.connect`.
- All existing behaviour and messages otherwise preserved; full suite + ruff
  green.

## Answer

**Built.** `computer_history/store/opening.py` holds the one entry point:

```python
open_store(db_path, purpose: Purpose) -> OpenedStore
Purpose:    READ | WRITE | WRITE_EXISTING
StoreState: READY | MISSING | OUTDATED | NEWER | BUSY | UNREADABLE
OpenedStore(path, state, supported, version=None, error=None, conn=None)  # context manager closes conn
```

`conn` is set only when `state is READY`. The lifecycle rules are all inside:
READ never creates or migrates and refuses any version mismatch (OUTDATED /
NEWER); WRITE creates and migrates; WRITE_EXISTING migrates but reports
MISSING instead of creating; NEWER is reported for every purpose without
writing; `sqlite3.Error` while opening maps to BUSY (SQLITE_BUSY/LOCKED by
error code) or UNREADABLE (anything else, e.g. "file is not a database").

`cli/db.py` shrank to message mapping: `store_unavailable(store)` prints the
reason (+ the busy hint for BUSY) and returns 1; `outdated_note` is shared
with status. All four commands use `open_store`; `_read_cursors` and the
CLI's `exists()`/version checks are gone.

**Decisions.**

- *rebuild-signals* uses `WRITE_EXISTING` (write-but-refuse-missing) rather
  than read-then-write: one open, no window between the check and the write,
  and the missing case keeps its old message via the mapper. It is opened
  with SQLite `mode=rw`, so even a race can't create the file.
- *backfill*: dry run opens READ (missing → plan without cursors, outdated →
  refused). A real run opens `WRITE_EXISTING` first and reads cursors from
  that connection; if the DB is missing it plans without cursors and opens
  WRITE only after planning succeeds. This keeps the existing guarantee
  (tested twice) that AW being down or a planning failure creates nothing.
  The DB is now opened before AW is contacted, so a newer/busy/unreadable DB
  is refused even when AW has no sources.
- *Busy means contention while opening* (migration, WAL switch), not a lock
  reservation. A ready DB opens READY even while another connection holds
  the write lock; later contention is handled where it already was
  (`run_cycle`, backfill's per-chunk error, rebuild's error). A probe lock at
  open was rejected because `ingest --watch` started during a rebuild would
  exit instead of retrying next cycle.
- *UNREADABLE* was added beyond the required states: previously any open
  error printed the busy hint, and "file is not a database" crashed status and
  ingest with a traceback.
- *status on a newer schema* now exits 1 with the shared upgrade message on
  stderr (after the Database/ActivityWatch lines), as the acceptance requires;
  previously it printed a stdout note and exited 0.
- `migrate` raises `NewerSchema` (a `RuntimeError` subclass, same message), so
  a newer DB is caught even if another process migrates it between version
  check and migration.
- `connect_readonly` is no longer re-exported from `store`; `open_store(READ)`
  is the read path. `connect` stays exported as the raising write primitive
  that tests and fixtures use. `tests/test_standards.py` now also counts
  `open_store` as opening a connection (cli/ only).
- Tests drop the `cli_db.connect` monkeypatching: lock tests use real files
  (outdated DB + a second connection holding `BEGIN IMMEDIATE`) with
  `store.db.BUSY_TIMEOUT_SECONDS` patched to 50ms via a `quick_busy_timeout`
  fixture; `tests/db_states.py` builds each state.

**Review fixes.**

- Planning moved to `sources/backfill.plan_all_backfills(conn | None, client,
  *, now, start, end)`, beside `plan_backfill`: discovers sources, reads each
  cursor, plans each. `cmd_backfill` only opens the store and calls it.
- A `sqlite3.Error` while reading cursors during planning prints `cannot
  read <path>: <error>` and exits 1, as the old `_read_cursors` did (tested
  for run and dry run).
- `connect` raises `WalUnavailable` (a `RuntimeError` subclass) when WAL
  can't be enabled; `open_store` maps it to UNREADABLE (tested by a
  connection factory that fakes the journal-mode answer).
- `rebuild-signals` uses `with store:`; `_unavailable_reason` is private.

**Accepted trade-offs.**

- A real backfill on a missing database plans without cursors; if another
  process creates the database and sets cursors meanwhile, the run replays
  history idempotently (duplicates are skipped, an existing cursor is never
  moved). Tickets 02/03 rework planning.
- `cli/db.py` keeps its name to avoid a rename for a module that now only maps
  store states to messages.
