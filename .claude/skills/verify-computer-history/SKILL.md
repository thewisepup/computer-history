---
name: verify-computer-history
description: Drive the real computer-history CLI (ingest, status, backfill, rebuild-signals) against an isolated run with a seeded fake ActivityWatch and its own database and spool, and capture transcripts as proof. Use when asked to prove, demo or verify a CLI change end to end in the real app, beyond pytest.
---

# Verify computer-history

The user-facing surface is the `computer-history` CLI in this checkout's
`.venv`. It reads ActivityWatch over HTTP and the capture agent's spool
folder, and writes one SQLite database. The user's live setup runs on this
machine at all times: ActivityWatch on `127.0.0.1:5600`, the capture agent,
and a LaunchAgent running `ingest --watch` into
`~/Library/Application Support/ComputerHistory/`. A verification run touches
none of it. Every run gets its own database, spool and fake ActivityWatch
port, so runs sit side by side with the live setup and with each other.

All driving goes through one helper, `scripts/chv`, run from the repo root.
Its commands are the only stable handles; it strips `COMPUTER_HISTORY_*`
from the environment and passes `--db-path` and `--aw-url` itself.

```bash
C=.claude/skills/verify-computer-history/scripts/chv
```

## Launch

Needs the venv from `AGENTS.md` (`.venv/bin/computer-history` must exist).

```bash
eval "$($C up)"        # sets CHV_RUN in this shell; prints "chv: run <id> ready; evidence in <dir>"
```

Ready means `up` printed that line: it waits until the fake ActivityWatch
answers `/api/0/info` with this run's id. The database does not exist yet;
the first `ingest` (or `backfill`) creates and migrates it, exactly as for a
new user. `CHV_RUN` must be set in every later shell (`export CHV_RUN=<id>`),
since each Bash call starts fresh.

The fake ActivityWatch (`scripts/fake_aw.py`) serves the endpoints the CLI
reads, with the real API's range semantics, seeded relative to launch time:

- `aw-window`: 3 events on each of the last 3 days, 8 five-minute events
  over the last 40 minutes, then one growing event (`Cursor`, `live — chv`).
- `aw-afk`: one `not-afk` span per earlier day, one over the last 40
  minutes, then one growing event.
- `aw-web`: two 4-minute tabs in the last 40 minutes (the gaps between them
  are real coverage gaps).
- `POST /__chv/advance` (via `$C aw-advance`) closes both growing events and
  starts new ones, as a heartbeat would, so the next ingest has one settled
  event to insert.

## Doctor

```bash
$C doctor
```

Read-only. Every line must say `ok`: fake ActivityWatch pid alive and
started by this run, `/info` answering with this run id, port not 5600,
database inside the run folder (not the live one), CLI imported from this
checkout, checkout still at the revision the run started on, and any
`ingest --watch` pid ours. Run it first, and again whenever output looks
wrong. On any `FAIL`, run `$C down` and `$C up` again rather than driving.

## Drive

| Command | Does |
|---|---|
| `$C cli <command> [flags]` | Runs `computer-history --db-path <run db> <command> [--aw-url <fake>] [flags]`; `--aw-url` is added for `ingest`, `status`, `backfill`. The spool defaults to `spool/` beside the run's database. Exits with the CLI's exit code. |
| `$C spool-seed` | Writes `fixtures/spool/records.jsonl` (14 records: 4 captures, 1 excluded, paused, resumed, slept, woke, and 5 screenshot records, one per status; dated 2026-11-18) into the spool as a finished `*.jsonl` file. |
| `$C spool-seed --now` | Writes one fresh `capture` record timestamped now (makes the agent read `alive yes`). |
| `$C spool-seed --bad` | Writes a file with 2 valid records and one torn line (the ingest must reject the line and set the file aside). |
| `$C spool-ls` | Lists the spool tree, `unreadable/` included. |
| `$C sql "<SELECT ...>"` | Query on the run's database with `PRAGMA query_only=1` (writes are refused); refuses when the database does not exist yet. |
| `$C aw-advance` | Closes the growing ActivityWatch events (see Launch). |
| `$C watch-start` / `$C watch-stop` | Runs `ingest --watch` in the background (60s cycles, first cycle immediately) / stops it with SIGINT. |
| `$C runs` | Lists run folders on this machine as `live` or `stale`. |

The per-command recipes and what proves each one are in
[`features/README.md`](features/README.md). Read the index, then the feature
file for what you are verifying, and cover every entry point it lists.

## Evidence

Every `chv` command except `up`, `doctor` and `runs` writes a numbered
transcript to `output/verify/<CHV_RUN>/NN-<label>.txt` (gitignored): run id,
UTC time, the exact command, exit code, stdout, stderr. `run.txt` there
records the revision and the fake's URL; `down` adds `aw-requests.log`, every
request the CLI made to the fake. The watch log is `NN-watch.txt`.

Proof standards:

- Drive the CLI, never the Python functions behind it.
- Pair each action with a second, read-only view of its result: an `ingest`
  with a `sql` row count or a `status`; a spool change with `spool-ls`.
- Prove idempotence by repeating the action and showing `inserted 0`.
- `backfill --dry-run` claims to write nothing: prove it with `status`
  afterwards still reading `not created yet` (fresh run) or unchanged row
  counts.
- The only mock is ActivityWatch, behind its real HTTP API. The spool is a
  real folder the real ingest reads and deletes from.

## Cleanup

```bash
$C down
```

Stops the watch (if any) and the fake ActivityWatch, by the pids this run
recorded and only after checking their command lines name `CHV_RUN`, then
deletes the run's state folder (`$TMPDIR/chv/<CHV_RUN>`: database, spool,
pids). The evidence folder stays and `down` lists it. Run `down` after a
failed attempt too. `$C runs` finds stranded runs; for a `stale` one, delete
its folder under `$TMPDIR/chv/`; for a `live` one, `CHV_RUN=<id> $C down`.

## Other surfaces

- The Swift capture agent: `capture-agent/scripts/e2e.sh` drives a scripted
  agent session into a temp spool and ingests it (needs `swift`).
- The frozen POC (`history.py` REST + `history_mcp.py`): see `README.md`;
  out of scope until M6 replaces it.
