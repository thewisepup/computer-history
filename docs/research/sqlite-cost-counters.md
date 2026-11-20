# Which SQLite cost counters stay deterministic across macOS and CI Linux

Research for #53 (part of #51), 2026-11-19. Question: which work-based
counters can a CI performance gate rely on to give identical, or tightly
bounded, numbers for the same synthetic database and code, when local dev runs
Homebrew Python 3.12 on macOS and CI runs `actions/setup-python` 3.12 on
`ubuntu-latest`?

## Short answer

| Counter | Same SQLite build, run to run | 3.45.1 (CI) vs 3.54.1 (local) | Gate on |
|---|---|---|---|
| VM steps via `set_progress_handler(h, 1)` | identical | differs by up to about 0.4% | per-version baseline, or a tolerance of about 2% |
| Statements via `set_trace_callback` | identical | identical | exact |
| `EXPLAIN QUERY PLAN` contains no `SCAN <table>` | identical | identical in our queries | exact, on a narrow pattern |
| `PRAGMA page_count` after checkpoint | identical | identical | exact |
| File bytes, sha256 | identical | differs (header, compile options) | do not gate |

Pin the inputs that move these numbers: `runs-on: ubuntu-24.04` rather than
`ubuntu-latest`, never run `ANALYZE` (or ship a fixed `sqlite_stat1`), warm the
statement cache before counting, and log `sqlite3.sqlite_version` with
`PRAGMA compile_options` in every gate run.

## Which SQLite each side runs

- **Local:** Homebrew `python@3.12` 3.12.16 reports `sqlite3.sqlite_version`
  **3.54.1**. Its `_sqlite3` extension links
  `/opt/homebrew/opt/sqlite/lib/libsqlite3.dylib`, which is the Homebrew
  `sqlite` formula (checked with `otool -L`). So a `brew upgrade sqlite`
  changes the SQLite version under an unchanged Python.
- **CI:** `ubuntu-latest` maps to Ubuntu 24.04
  ([runner-images README](https://github.com/actions/runner-images/blob/main/README.md)).
  Image 20261111.370.1 lists Python 3.12.16 in the tool cache and
  `libsqlite3-dev` / `sqlite3` **3.45.1-1ubuntu2.9**
  ([Ubuntu2404-Readme.md](https://raw.githubusercontent.com/actions/runner-images/main/images/ubuntu/Ubuntu2404-Readme.md)).
  The tool-cache Python is built from source on the image with
  `apt install libsqlite3-dev` and `./configure --enable-shared
  --enable-optimizations --enable-loadable-sqlite-extensions`
  ([ubuntu-python-builder.psm1](https://raw.githubusercontent.com/actions/python-versions/main/builders/ubuntu-python-builder.psm1)).
  It therefore links the system `libsqlite3.so.0`, so CI's SQLite is the
  Ubuntu package (3.45.1), not a copy bundled with Python. *Not verified on a
  live runner*; the gate should print the version to confirm.
- The same builder already has a branch for Ubuntu 26.04. When `ubuntu-latest`
  moves (the README says `-latest` labels move to the newest stable OS over
  1 to 2 months), CI's SQLite jumps with it. Pin `ubuntu-24.04`.
- **Compile options differ as well as versions.** Homebrew's build has
  `ENABLE_STAT4` and no `SECURE_DELETE` (from `PRAGMA compile_options`).
  Ubuntu noble's `debian/rules` sets `-DSQLITE_SECURE_DELETE` and
  `-DSQLITE_ENABLE_UPDATE_DELETE_LIMIT=1` among others, with no `STAT4`
  ([launchpad noble-updates debian/rules](https://git.launchpad.net/ubuntu/+source/sqlite3/plain/debian/rules?h=ubuntu/noble-updates)).
  `STAT4` changes plans whenever `ANALYZE` has run.

## Method of the local experiments

There is no Docker here, so CI's library was reproduced by building the
3.45.1 amalgamation from sqlite.org with Ubuntu's `debian/rules` flags into a
dylib and loading it under the same Homebrew Python via `DYLD_LIBRARY_PATH`.
A 3.54.1 build with the same Ubuntu flags separates version effects from
compile-option effects. Four runs:

- `brew`: Homebrew 3.54.1, Homebrew flags.
- `brew2`: the same build again, in a fresh process.
- `345`: 3.45.1 with Ubuntu flags, the stand-in for CI.
- `3541u`: 3.54.1 with Ubuntu flags.

The database is the repo's real schema (`computer_history/store/migrations/*.sql`)
with 20,000 seeded `observations` rows, one `signals` row each, in WAL mode,
as `store.db.connect` opens it. Five queries:

- `obs_range`: an indexed range on `(source, started_at)`.
- `sig_range`: an indexed range plus `GROUP BY`.
- `join`: `signals` joined to `observations` by primary key.
- `full_scan`: `payload LIKE`.
- `or_terms`: an `OR` across two indexed columns.

## 1. `set_progress_handler` as a VM-instruction counter

What the sources say:

- SQLite: "N is the **approximate** number of virtual machine instructions that
  are evaluated between successive invocations". Since 3.41.0 the handler
  "might also be invoked directly from `sqlite3_prepare()` while analyzing and
  generating code for complex queries"
  ([progress_handler](https://www.sqlite.org/c3ref/progress_handler.html);
  [changes 3.41.0](https://www.sqlite.org/changes.html)).
- CPython forwards `n` unchanged to `sqlite3_progress_handler(self->db, n, ...)`.
  A truthy return aborts the query
  ([connection.c, 3.12](https://raw.githubusercontent.com/python/cpython/3.12/Modules/_sqlite/connection.c);
  [docs](https://docs.python.org/3.12/library/sqlite3.html)).
- The meaning of "approximate" is in `vdbe.c`. `nVmStep` increments on every
  opcode, but the check runs only at `check_for_interrupt`: `OP_Goto`,
  `OP_Gosub`, and the loop-bottom opcodes (`OP_Next` and the like). There it
  calls the handler in a `while (nVmStep >= nProgressLimit)` loop, so it
  catches up. The first limit is phased by the statement's running
  `SQLITE_STMTSTATUS_VM_STEP` counter
  ([vdbe.c](https://raw.githubusercontent.com/sqlite/sqlite/master/src/vdbe.c)).
  With `n=1`, the call count equals the VM steps executed up to the last
  loop-back check, plus any calls made during prepare. That is deterministic:
  no clock or randomness is involved. It misses only the straight-line opcodes
  after the last check.

What the experiments showed:

- **Run to run on one build, the count is exact.** Five repeats and a second
  process returned identical counts for every query, for example
  `full_scan` = 86,785 and `or_terms` = 110,011 both times.
- **The first execution of an SQL text costs more.** `sig_range` counted
  80,067 on its first run and 80,063 afterwards; `join` counted 2,307, then
  2,304. That is the 3.41+ prepare-time invocation on a statement-cache miss.
  CPython's statement cache absorbs it after the first run.
- **The first statement on a fresh connection adds about 154 steps.** That is
  the schema load (154 on 3.54.1). So a gate must either warm up (run the
  query once and count the second run) or always count from a fresh
  connection. It must not mix the two.
- **Granularity with `n>1`:** the count times `n` is quantized to `n` and
  phase-shifted. At `n=1000`, `join` reported 3,000 against an exact 2,304,
  and `obs_range` reported 5,000 against 5,269. Only `n=1` is an exact
  counter.
- **Overhead:** at `n=1` a Python callback runs per check, which made queries
  2 to 8 times slower: `obs_range` 0.029 to 0.245 ms, `sig_range` 0.70 to
  3.9 ms, `full_scan` 3.5 to 7.4 ms. At `n=1000` the overhead could not be
  measured. Fine for a gate on synthetic data of this size. For a 1M-row
  dataset, expect seconds per query.
- **Across versions the counts drift, slightly but not exactly.** With no
  `ANALYZE`, 3.45.1 against 3.54.1 (same flags): `sig_range` 80,062 against
  80,063, and `full_scan` 86,786 against 86,785. First-run `obs_range` was
  5,275 against 5,269. With `ANALYZE`, `or_terms` was 3,286 against 3,273
  (+0.4%). Compile options alone (Homebrew against Ubuntu flags on 3.54.1)
  gave identical counts without `ANALYZE`. With `ANALYZE` they differed
  (`sig_range` 80,071 against 80,067), because Homebrew's STAT4 writes 72
  `sqlite_stat4` rows that the Ubuntu build ignores.
- Python's `sqlite3` does not expose `sqlite3_stmt_status(SQLITE_STMTSTATUS_VM_STEP)`,
  the exact per-statement counter. The progress handler at `n=1` is the only
  way to reach it from the stdlib.

## 2. `set_trace_callback` for counting statements

- CPython registers `sqlite3_trace_v2(db, SQLITE_TRACE_STMT, ...)` and passes
  `sqlite3_expanded_sql(stmt)` to Python (bound parameters inlined). It falls
  back to the unexpanded text only if expansion fails
  ([connection.c](https://raw.githubusercontent.com/python/cpython/3.12/Modules/_sqlite/connection.c)).
- SQLite fires `SQLITE_TRACE_STMT` "when a prepared statement first begins
  running and possibly at other times ... such as at the start of each trigger
  subprogram". For a trigger, X is an SQL comment beginning with `--`
  ([c_trace](https://www.sqlite.org/c3ref/c_trace.html)).
- **Pitfall: triggers appear as duplicates.** Because CPython ignores X and
  always expands the outer statement, each trigger event arrives as a copy of
  the outer SQL. The sqlite3 CLI shows the raw events for one insert into a
  table with one `AFTER INSERT` trigger:
  `INSERT INTO a VALUES (1);`, `-- TRIGGER tr;`, `-- INSERT INTO b VALUES (new.x);`.
  Python received `INSERT INTO a VALUES (1)` three times. The repo's
  `observations_no_update` trigger produced three identical `UPDATE` lines
  before the abort. So the trace count is top-level statements plus trigger
  events, and the two cannot be told apart from the text.
- **`executemany` traces once per parameter row** (each reset and re-step
  fires again): three rows gave three `INSERT` lines with the values inlined.
  `executescript` traces each statement, with its original whitespace and
  semicolon.
- **Implicit transactions are traced.** Under the legacy default
  `isolation_level=""`, the module's own `BEGIN ` and `COMMIT` appear, as the
  docs warn ("transaction management of the sqlite3 module and the execution
  of triggers"). The store opens with `isolation_level=None`, so only explicit
  `BEGIN IMMEDIATE` / `COMMIT` appear there.
- Not reported: the schema reads SQLite runs internally, and the work inside a
  statement (row counts). Trace says how many statements ran, not how
  expensive they were.
- Identical across all four builds in our runs. Trace events depend on the
  code path, not the planner, so this count is safe to gate on exactly.

## 3. `EXPLAIN QUERY PLAN` to assert "no full SCAN"

- The docs say the output "is intended for interactive debugging only. The
  output format may change between SQLite releases. Applications should not
  depend on the output format". The format "did change substantially" in
  3.24.0 and had "minor changes" in 3.36.0
  ([eqp.html](https://www.sqlite.org/eqp.html)). 3.48.0 "Improved EXPLAIN
  QUERY PLAN output for covering indexes"
  ([changes](https://www.sqlite.org/changes.html)).
- The rows are `(id, parent, notused, detail)`. In `detail`, `SCAN` means
  every row is visited, "including cases where SQLite iterates through all
  records in a table in an order defined by an index". `SEARCH` means a subset
  is visited. Since 3.36 the form is `SCAN t1`, not `SCAN TABLE t1`.
- In our runs, 3.45.1 and 3.54.1 produced byte-identical detail strings for all
  five queries, both with and without `ANALYZE`, for example
  `SEARCH observations USING COVERING INDEX observations_source_started_at (source=? AND started_at>? AND started_at<?)`.
- A safe assertion is narrow. For a query on an indexed table, check
  `not re.match(r"SCAN (\w+)", detail)` on each row's `detail`, and accept any
  `SEARCH`. Do not snapshot the full strings; wording such as
  `COVERING INDEX`, `(rowid=?)` and `MULTI-INDEX OR` changes between releases.
  Watch the legitimate scans: `SCAN` over a covering index for an ordered
  read, a `SCAN` of a CTE or subquery, `USE TEMP B-TREE`. Allow those per
  query.
- **The plan itself depends on statistics.** `or_terms` was `SCAN observations`
  (110,011 steps) without stats and `MULTI-INDEX OR` over two indexes (3,273
  steps, 33 times fewer) after `ANALYZE`, on both versions. An EQP gate is
  only meaningful if the gate controls whether `sqlite_stat1` exists.

## 4. `PRAGMA page_count` and file size

- `page_count` was identical across all four builds and runs: 2,520 pages at
  4,096 bytes; 1,249 at `page_size=8192`; 2,472 after `VACUUM`. `dbstat`
  per-table page counts were also identical (for example `observations` 1,659
  and `observations_source_started_at` 179). The B-tree layout for identical
  inserts in identical order is deterministic, and no change to the default
  page size or file format appears between 3.41 and 3.54
  ([changes](https://www.sqlite.org/changes.html)).
- **WAL:** committed pages can sit in `-wal` until a checkpoint
  ([fileformat2](https://www.sqlite.org/fileformat2.html)). `PRAGMA page_count`
  reads through the WAL, so it is right either way. The main file's byte size
  and the `-wal` size depend on auto-checkpoint timing (the default is 1,000
  pages). Our build wrote 10.5 MB of WAL. Measure `page_count`, or run
  `PRAGMA wal_checkpoint(TRUNCATE)` first if you need the file size.
- `page_size` changes the count, so pin it (default 4,096 in both builds).
  `VACUUM` repacks the pages (2,520 to 2,472) and also writes a full copy
  through the WAL. Gate either always-vacuumed or never-vacuumed sizes, and
  never compare one against the other. `freelist_count` was 0. A workload with
  deletes leaves free pages, and `page_count` includes them.
- **The bytes are not portable.** File body hashes (bytes after the 100-byte
  header) matched between 3.45.1 and 3.54.1 with the same flags, but differed
  from Homebrew's build. Full-file hashes always differ across versions,
  because header offset 96 stores the `SQLITE_VERSION_NUMBER` of the last
  writer ([fileformat2](https://www.sqlite.org/fileformat2.html)).
  `SECURE_DELETE` (Ubuntu) also zeroes freed content. Never gate on a file
  hash.

## 5. What shifts between SQLite versions

- **Stable across 3.45.1 and 3.54.1 here:** `page_count`, `dbstat` page
  counts, trace statement counts, and EQP plan choice and wording for these
  queries.
- **Shifts slightly:** VM step counts (0 to 0.4% in our sample). The changelog
  between the two versions lists planner and code-generation work in nearly
  every release. Examples: 3.46.0 VALUES-as-coroutine and push-down; 3.47.0
  Bloom filters on IN subqueries; 3.49.0 star-join plans; 3.51.0 early
  detection of empty joins and EXISTS-to-JOIN; 3.53.0 sort-and-merge for
  compound queries; 3.54.0 `expr OR TRUE` folding
  ([changes](https://www.sqlite.org/changes.html)). Simple indexed lookups
  barely move. Joins, subqueries, `EXISTS`, `IN` and compound selects can move
  a lot, and can change plan.
- **Statistics:** 3.45.0 changed how the planner treats indexes `ANALYZE`
  marks low-quality. 3.46.0's `PRAGMA optimize` applies an analysis limit
  automatically and re-analyzes tables that have no `sqlite_stat1` rows. 3.47.0
  stopped creating automatic indexes on columns known to be non-selective
  ([changes](https://www.sqlite.org/changes.html)). So `PRAGMA optimize`
  behaves differently on 3.45.1 and 3.54.1, and STAT4 exists only in the
  Homebrew build. Any gate database that has run `ANALYZE` or `optimize` can
  plan differently on the two machines.

## 6. Recommendation

**Safe to gate on exactly** (same synthetic DB, same code):

1. Number of statements traced per operation, with `isolation_level=None` as
   the store uses. Count all lines, accepting that trigger events show up as
   duplicates (each operation's count is still stable). This catches N+1
   regressions directly.
2. No `SCAN <indexed table>` in EQP for the queries meant to use an index,
   matched with a narrow regex and a per-query allowlist.
3. `PRAGMA page_count` (and `dbstat` per table) for a database built by a
   fixed insert sequence with `page_size` pinned. Compare like with like on
   `VACUUM`.

**Need a tolerance or a per-version baseline:**

4. VM steps at `n=1`. Use one of two options:
   - Store the baseline keyed by `sqlite3.sqlite_version` plus a hash of
     `PRAGMA compile_options`, and fail on any increase. Regenerate it when
     the key changes.
   - Use one cross-platform baseline with a tolerance of about 2% (ten times
     the drift seen), and accept that a 3.45 to 3.5x jump in complex queries
     can exceed it.

   Count the second execution of each statement on a warmed connection, never
   the first, and never at `n>1`. If the gate runs only on CI, a single
   baseline from the pinned runner can be exact; developers then see "within
   tolerance" locally and the exact verdict in CI.

**Pitfalls to design around:**

- `ubuntu-latest` will move to 26.04, which brings a new SQLite. Pin
  `ubuntu-24.04`, and make version changes deliberate.
- `brew upgrade sqlite` silently changes local counts without changing Python.
- Never run `ANALYZE` or `PRAGMA optimize` on the gate database, or commit a
  fixed `sqlite_stat1` and load it with `ANALYZE sqlite_schema`. STAT4
  (Homebrew only) would still differ, so the plain no-stats setup is simplest.
- The statement cache and schema load add steps on first use (+4 to +6 and
  +154 here). Warm up first.
- Leave the progress handler off outside measurement: at `n=1` it slows
  queries 2 to 8 times.
- Each gate log should record `sqlite_version`, `compile_options`,
  `page_size` and `journal_mode`, so a red gate can be told apart from an
  environment change.

## Not proven

- CI's actual `sqlite3.sqlite_version` was inferred from the runner image
  listing and the builder script, not printed on a live runner.
- The 3.45.1 stand-in was built with clang on macOS. Ubuntu's own build uses
  gcc with distro patches (for example the 2.9 security fixes). VM step counts
  come from code generation, not the C compiler, but distro patches could
  differ slightly.
- Five queries on one schema: drift on joins, subqueries and `EXISTS` is likely
  larger than the 0.4% seen here.
