# computer-history CLI

The command line for the local activity store: it ingests settled
ActivityWatch events and the capture agent's spool into SQLite and reports on
what is stored. Each command parses its flags, calls one function in the
layers below and formats the result; `computer_history/cli/__init__.py` maps
the modules. This page shows how to run each command and what it prints.
`docs/DESIGN.md` has the full rules for the stable install's commands
(`install`, `update`, `rollback`, `backup`, `restore`: §8.5), `watchdog`
(§8.6) and `status` (§8.7).

Run it as `.venv/bin/computer-history`, or bare `computer-history` with the
venv activated (or aliased). `-h` on any command prints its flags.

## Profiles: stable and dev

Every run is **dev** unless its code runs from the stable install: a version
folder under `~/Library/Application Support/ComputerHistory/versions/` that
carries the `installed` marker. A checkout, a worktree, an editable install, a
`pip install .` into a venv, or a version folder without the marker is dev.
`computer-history install` sets the stable install up and links it on the
PATH as `~/.local/bin/computer-history`; the checkout's
`.venv/bin/computer-history` stays dev.

| | dev | stable |
|---|---|---|
| Data folder | `~/Library/Application Support/ComputerHistory-dev/` | `~/Library/Application Support/ComputerHistory/` (the live folder) |
| Database, spool, screenshots | `history.db`, `spool/`, `screenshots/` in that folder | the same, in the live folder |
| Live folder | refused | its own |
| ActivityWatch | reads the live one | reads the live one |

`--db-path`, `$COMPUTER_HISTORY_DB`, `--spool-path` and `$COMPUTER_HISTORY_SPOOL`
still win over the defaults, but dev refuses, with exit code 1, any of them
inside the live folder, including through a symlink or in another letter case.
The screenshots sit beside the database, so the database's refusal covers them.
The capture agent writes into the live folder, so a dev `ingest` with no flags
reads ActivityWatch and an empty dev spool. `dev build-db`, `dev perf` and
`dev bench` open neither the database nor the spool, so they are never
refused; `dev snapshot` is the one command that reads live data from dev.

Every command's first line names the profile, the version (stable) or the
checkout's branch and commit (dev), and what the command uses. Real output,
home shortened to `~`:

```
$ computer-history status
Profile dev (branch 103-dev-profile-data-folder at f8ea2fb), database ~/Library/Application Support/ComputerHistory-dev/history.db
...
$ computer-history --db-path ~/Library/Application\ Support/ComputerHistory/history.db ingest
Profile dev (branch 103-dev-profile-data-folder at f8ea2fb), database refused
refused: ~/Library/Application Support/ComputerHistory/history.db is in the live data folder ~/Library/Application Support/ComputerHistory. This run is dev (its code is a checkout or worktree, not the stable install), and dev never uses live data. Leave --db-path and $COMPUTER_HISTORY_DB unset to use ~/Library/Application Support/ComputerHistory-dev/history.db, or run the stable install's computer-history.
```

Stable prints `Profile stable (version 1a2b3c4), database ~/Library/Application Support/ComputerHistory/history.db`.
Dev reads the branch and commit from the checkout's `.git` without running
git: `(branch main, no commits yet)` before the first commit, `(detached at
<commit>)` on a detached HEAD, `(an installed copy, not a checkout)` for a copy
in a venv's `site-packages`, and `(not a git checkout)` otherwise.

## install and uninstall — the stable install

```bash
brew install uv                      # once: install builds with uv
.venv/bin/computer-history install   # from a checkout; safe to re-run
computer-history uninstall           # LaunchAgents, versions and the link; never the data
```

`install` builds the newest `main` commit that passed the release gate
(`RELEASE_GATE` in `computer_history/stable/gate.py`) into
`versions/<short commit>/`, points `current` at it, links
`~/.local/bin/computer-history`, removes the stopgap backend LaunchAgent and
loads the backend, daily backup, watchdog and ActivityWatch LaunchAgents. Run
again with a current version, it skips GitHub and `uv` and only repairs the
link, the plists and the stopgap. Real output through the CLI with the test
suite's fake host adapter, in a temporary home (live folder shortened to
`.../ComputerHistory`):

```
$ .venv/bin/computer-history install
Profile dev (branch 106-install-stable at f3eb7a0), stable install ~/Library/Application Support/ComputerHistory
Release gate: lint, unit, data, poc, secrets, macos-capture-agent-tests, macos-capture-agent-e2e
  skipped 5e26ac9: unit failure
Installed version 572c48b (commit 572c48b111111111111111111111111111111111)
  current       .../ComputerHistory/current -> .../ComputerHistory/versions/572c48b
  PATH link     ~/.local/bin/computer-history -> .../ComputerHistory/current/venv/bin/computer-history
  stopgap       io.github.thewisepup.computer-history.backend booted out and removed
  LaunchAgent   io.github.thewisepup.computer-history.ingest loaded: computer-history ingest --watch, restarted by launchd at most every 30s
  LaunchAgent   io.github.thewisepup.computer-history.backup loaded: computer-history backup, daily at 03:00 and at login
  LaunchAgent   io.github.thewisepup.computer-history.watchdog loaded: computer-history watchdog, every 60s
  LaunchAgent   io.github.thewisepup.computer-history.activitywatch loaded: /usr/bin/open -g -b net.activitywatch.ActivityWatch, once at login
```

Offline, without `uv`, with no passing commit among the newest 20, or when a
file can't be written, it exits 1 and removes whatever it created. A file at
`~/.local/bin/computer-history` that is not the install's own link is refused,
never replaced. `$GITHUB_TOKEN`, when set, lifts GitHub's 60-requests-an-hour
limit.

```
install failed: uv is not installed (install it with `brew install uv`) (nothing was changed)
```

`uninstall` removes the LaunchAgents, the link (only when it is the install's
own), `current` and `versions/`, and keeps the data, logs and backups.

## --spool-reads — what this code reads from the spool

```bash
computer-history --spool-reads
```

Prints the spool version and record kinds this code's backend reads, as one
JSON line, and exits before any command runs (no profile line, no database).
It is hidden from `--help`: nothing in this code reads the answer, but stable
versions from before rollback stopped moving the capture agent ask it of
every version they build, and fail the build without it. Real output:

```
{"spool_version": 1, "kinds": ["capture", "excluded", "paused", "resumed", "slept", "woke", "screenshot"]}
```

## update and rollback — moving the stable install

```bash
computer-history update              # to the newest main commit that passed the release gate
computer-history update --wait 1800  # wait up to 30 minutes for the first cycle (default 600s)
computer-history rollback            # back to the previous version; no network
```

`update` only moves forward. It builds the new commit beside `current` (and
its capture agent, when `capture-agent/` changed), takes a pre-update backup,
switches `current` and restarts the backend, then waits for the backend's
first ingest cycle. An ok cycle keeps the new version and swaps a changed
capture agent; a failed, crashed or missing cycle falls back to the old
version. **A long migration needs a longer `--wait`.** Exit codes: 0 updated
(or already up to date), 1 failed or fell back, 3 the capture agent fell back,
130 interrupted. Every update, fallback and rollback appends a line to
`update-log.jsonl` in the live folder, and `status` shows the last one.
`docs/DESIGN.md` §8.5 has every step and branch.

Real output through the CLI with the test suite's fake host adapter:

```
$ computer-history update
Profile stable (version 572c48b), stable install .../ComputerHistory
Release gate: lint, unit, data, poc, secrets, macos-capture-agent-tests, macos-capture-agent-e2e
  skipped 9f0e1d2: unit failure
Updated to version 8d23e3a (commit 8d23e3a222222222222222222222222222222222) from 572c48b
  backup        .../ComputerHistory/backups/pre-update/history-2026-11-20T191952-572c48b.db (schema v5)
  first cycle   completed; the backend deletes stored spool files again
  current       .../ComputerHistory/current -> .../ComputerHistory/versions/8d23e3a
  previous      572c48b (rollback returns to it)
  agent         updated and verified: the new capture agent records
$ computer-history update
Profile stable (version 8d23e3a), stable install .../ComputerHistory
Release gate: lint, unit, data, poc, secrets, macos-capture-agent-tests, macos-capture-agent-e2e
Update to version 9f0e1d2 fell back: the backend crashed before its first ingest cycle
  backup        .../ComputerHistory/backups/pre-update/history-2026-11-20T191952-8d23e3a.db (schema v5)
  database      kept as it is (the schema did not change)
  backend       restarted on 8d23e3a; it reads the spool files it kept again
```

`rollback` points `current` at the previous version and restarts the backend;
running it twice returns to where it started. The capture agent stays as it
is: a spool file holding a record kind or spool version the older backend
can't read has its other records stored and is moved to `spool/unreadable/`,
never deleted. Once a version that reads it is current again, move the file
back into `spool/` to ingest it. Output from the tests' fake host
(illustrative names):

```
$ computer-history rollback
Profile stable (version 8d23e3a), stable install .../ComputerHistory
Rolled back to version 572c48b from 8d23e3a
  previous      8d23e3a (rollback again returns to it)
  agent         left as it is (8d23e3a's build)
  backend       restarted
  note: spool files 572c48b can't read are moved to .../ComputerHistory/spool/unreadable/, not deleted
```

It never restores a backup, so when the database's schema is newer than the
previous version opens, it refuses (illustrative):

```
rollback failed: the database is at schema v6, newer than version 572c48b can open (v5); put its pre-update backup back first with `computer-history restore .../backups/pre-update/history-2026-11-20T191952-572c48b.db`, then roll back (nothing was changed)
```

`install`, `uninstall`, `update`, `rollback` and a stable `restore` take turns
on one lock on the live folder; a second one exits 1 at once (`update refused:
another install, uninstall, update, rollback or restore is using
.../ComputerHistory; run it again once that one has finished`).

## check-agent-install — guarding the capture agent's hand install

```bash
capture-agent/scripts/install.sh            # runs the guard first; a refusal stops it before the build
capture-agent/scripts/install.sh --force    # passes --force on: install anyway, listing what was skipped
.venv/bin/computer-history check-agent-install [--force]   # the guard alone
```

The capture agent's install script asks this command first. It allows the
install only when all of these hold for the checkout the command's own code
runs from (whatever the current directory; `GIT_DIR` and friends are ignored):

| Condition | Unmet when | Fix it names |
|---|---|---|
| on main | another branch, or HEAD detached | `git switch main` |
| clean working tree | `git status --porcelain` lists anything, untracked files included | commit or stash |
| HEAD is origin/main | they differ, or there is no `origin/main` (read locally; nothing is fetched) | `git pull` / `git fetch origin main` |
| capture-agent checks passed on HEAD | `macos-capture-agent-tests` or `macos-capture-agent-e2e`, the release gate's capture-agent checks, failed, was cancelled, is still running or never ran | wait for CI if running; re-run CI or check the job name if it never ran; else fix and re-run |
| stable backend at HEAD or newer | there is no stable install, or `current` is not HEAD and is a version older than HEAD among `main`'s newest 20 commits (the release gate's walk, never local ancestry), or HEAD is not among them | `computer-history install` / `update` / `git pull` |

Every unmet condition is listed with its fix on stderr, and the exit code is
1; GitHub out of reach refuses too. `--force` exits 0 and lists what it
skipped. Real output through the CLI with the test suite's fake host adapter:

```
$ .venv/bin/computer-history check-agent-install
Profile dev (branch main at 572c48b), stable install .../ComputerHistory
Agent install refused: 3 unmet conditions for HEAD 572c48b (pass --force to install anyway)
  clean working tree: the working tree has uncommitted changes; commit or stash them
  capture-agent checks passed on HEAD: macos-capture-agent-e2e running; wait for CI to finish on it
  stable backend at HEAD or newer: the stable backend is version 5e26ac9, older than HEAD 572c48b; move it forward first: computer-history update
```

With every condition met it prints `Agent install allowed: every condition
holds for HEAD 572c48b` and exits 0.

## backup and restore — the daily backup and putting one back

```bash
computer-history backup                    # today's backup, unless it is taken already
computer-history restore 2026-11-19        # put that day's backup in the database's place
computer-history restore <backup file>     # anything not written YYYY-MM-DD is a file path
```

`backup` copies the database with SQLite's online backup (the backend keeps
writing) into `backups/daily/history-<day>.db` beside it, keeps the copy only
if it passes `PRAGMA integrity_check`, and removes the days past the newest
seven. Only the database is backed up, never the spool or the screenshots. The
stable install runs it at 03:00 and at login.

`restore` sets the current database aside in `backups/set-aside/` (never
deleted) and copies the backup in. On the live database it first stops the
backend, the watchdog and the daily backup, and starts them again after. It
refuses while anything else has the database open, such as an `ingest
--watch` in a terminal. To undo a wrong restore, restore the set-aside file by
path. Spool records ingested after the backup was taken are only in the
set-aside copy, since spool files are deleted once stored.

Real output through the CLI with the test suite's fake host adapter:

```
$ computer-history backup
Profile stable (version 572c48b), database .../ComputerHistory/history.db
Backed up .../ComputerHistory/history.db
  copied to .../ComputerHistory/backups/daily/history-2026-11-20.db
  schema v5, 92.0 KB, integrity ok
$ computer-history restore 2026-11-19
Profile stable (version 572c48b), database .../ComputerHistory/history.db
Restored the daily backup of 2026-11-19 into .../ComputerHistory/history.db
  from          .../ComputerHistory/backups/daily/history-2026-11-19.db
  set aside     .../ComputerHistory/backups/set-aside/history-2026-11-20T183735.db (never deleted)
  backend       io.github.thewisepup.computer-history.ingest stopped, then started again
  watchdog      io.github.thewisepup.computer-history.watchdog stopped, then started again
  backup        io.github.thewisepup.computer-history.backup stopped, then started again
$ computer-history restore 2026-01-02
Profile stable (version 572c48b), database .../ComputerHistory/history.db
restore failed: no daily backup of 2026-01-02; the kept ones are 2026-11-19, 2026-11-20 (nothing was changed)
```

## watchdog — is anything silent?

```bash
computer-history watchdog                       # what the watchdog LaunchAgent runs every minute
.venv/bin/computer-history watchdog --db-path /tmp/scratch/history.db --aw-url http://127.0.0.1:5666/api/0
```

One run checks the capture agent, ActivityWatch and the backend, posts a
macOS notification for each problem (at most once an hour each) and once when
it clears, reopens ActivityWatch when it is down (at most three times an
hour), saves its findings to `watchdog.json` beside the database, and exits 0.
The capture agent and the backend are problems only while aw-afk shows you
active; after a sleep, silence counts from the first run after waking.
`docs/DESIGN.md` §8.6 has the rules.

Each is silent after 5 minutes unless the agent's config file beside the
database (`agent-config.json`) says otherwise; values run from 1 to 1440, and a
bad one falls back to 5 and is shown as a `config problem:` line:

```json
{"watchdog": {"capture_agent_minutes": 10, "activitywatch_minutes": 5, "backend_minutes": 15}}
```

Real output through the CLI with the test suite's fake host adapter and fake
ActivityWatch, the capture agent stopping after minute 2:

```
$ computer-history watchdog          # minute 8
Profile stable (version bbbbbbb), database ~/Library/Application Support/ComputerHistory/history.db
Watchdog (silent after: capture agent 5m, ActivityWatch 5m, backend 5m)
  capture agent  PROBLEM: silent while you were active, last seen 2026-11-17 02:02 (6m ago)
  ActivityWatch  ok: recording, last seen 2026-11-17 02:08 (0s ago)
  backend        ok: recording, last seen 2026-11-17 02:08 (0s ago)
  notified: The capture agent has recorded nothing for over 5 min while you were active.
```

A run that finds another still holding `.watchdog.lock` exits 0 without a
word past the profile line.

## ingest — the everyday command

```bash
computer-history ingest            # one poll: catch up from where the last one stopped
computer-history ingest --watch    # poll every 60s until Ctrl-C
```

```
Profile stable (version 1a2b3c4), database .../ComputerHistory/history.db
Ingested from http://127.0.0.1:5600/api/0 and .../ComputerHistory/spool into .../ComputerHistory/history.db
  aw-afk     inserted      5  skipped      0  held back   1
  aw-web     inserted     62  skipped      1  held back   0
  aw-window  inserted    271  skipped      1  held back   1
  ax-text    inserted    412  skipped      0  held back   0  rejected 1
  screenshot inserted    410  skipped      0  held back   0
```

`inserted` is new rows, `skipped` is rows already stored (re-reads are
harmless), `held back` is ActivityWatch events still growing, which land on a
later poll, and `rejected` is spool lines that are not usable records. A spool
file is deleted once both its streams stored it; one with an unusable line is
moved into `spool/unreadable/` instead. One source failing (ActivityWatch
down, say) doesn't stop the other: its rows are stored and the run exits 1.

`--watch` is the long-running collector. It survives ActivityWatch outages and
locked databases, writes one record per cycle to stderr and to the JSON log,
and after every cycle rewrites `ingest-health.json` beside the database, which
`status`, the watchdog and `update` read. After 5 failed cycles in a row it
posts a notification (`ingest failing for 5 cycles. Run \`computer-history
status\`.`), at most hourly, and `ingest recovered.` once a cycle succeeds;
`COMPUTER_HISTORY_NOTIFY=0` turns notifications off. Real output from a run
where `ingest_progress` was renamed away for two cycles:

```
2026-11-20 17:15:32 INFO    sources.cycle_report  cycle ok: aw-afk +0 (1 dup, 1 held); aw-web +0 (0 dup, 0 held); aw-window +0 (3 dup, 1 held); ax-text +0 (0 dup, 0 held); screenshot +0 (0 dup, 0 held)  duration_ms=12
2026-11-20 17:16:32 ERROR   sources.cycle_report  cycle failed: ingest failed on aw-afk: database error: no such table: ingest_progress  duration_ms=2 retry_s=60 streak=1  exc="sqlite3.OperationalError: no such table: ingest_progress"
2026-11-20 17:17:32 ERROR   sources.cycle_report  cycle failed: ingest failed on aw-afk: database error: no such table: ingest_progress  duration_ms=1 retry_s=60 streak=2
2026-11-20 17:18:32 INFO    sources.cycle_report  cycle ok: aw-afk +0 (1 dup, 1 held); aw-web +0 (0 dup, 0 held); aw-window +0 (3 dup, 1 held); ax-text +0 (0 dup, 0 held); screenshot +0 (0 dup, 0 held)  duration_ms=20
2026-11-20 17:18:32 INFO    sources.cycle_report  ingest recovered  failed_cycles=2 failing_since=2026-11-21T01:16:32.792900+00:00
```

While `update` holds spool deletion (`spool-deletion-held` beside the
database), every ingest keeps the spool files it stores, and a one-shot run
ends with `spool files kept: ...`.

## status — is everything healthy?

```bash
computer-history status
computer-history status --spool-path /tmp/spool   # or $COMPUTER_HISTORY_SPOOL
```

```
Database:      .../ComputerHistory/history.db (5.2 MB, schema v5)
ActivityWatch: yes (http://127.0.0.1:5600/api/0; sources: aw-afk, aw-web, aw-window)
Ingest:        ok, last cycle 2026-11-18 10:10 (20s ago)

Sources:
  aw-window     3,451 observations  latest end 2026-11-18 10:10  settled until 2026-11-18 10:10 (5s behind now)
  ax-text         812 observations  latest end 2026-11-18 10:09  settled until 2026-11-18 10:09 (1m 10s behind now)
  ...
Coverage gaps (unobserved: nothing recorded) of 5m or more ...
  warning: no aw-web coverage from 2026-11-17 10:45 to 2026-11-17 12:25 (1h 39m)
  ax-text from 2026-11-17 10:09 to 2026-11-18 10:09 (unobserved: aw-afk shows you active, no record within 1m, not paused or asleep):
  warning: no ax-text coverage from 2026-11-18 08:02 to 2026-11-18 08:40 (38m), while you were active
  warning: no ax-text coverage from 2026-11-18 09:15 to 2026-11-18 09:27 (12m), cannot be judged: no aw-afk data
  screenshot: not checked (coverage is judged from ax-text records)

Capture agent:
  last capture  2026-11-18 10:09 (40s ago)
  alive         yes (last record 2026-11-18 10:10 (12s ago))
  spool         2 finished files waiting (oldest 1m 30s), 0 in unreadable/  (.../ComputerHistory/spool)
  today         812 captures stored, 14 excluded, 3 cut off, 1 timed out, 2 slept, 2 woke
  paused        no
  app agreement 1,602 of 1,615 captures match aw-window (13 differ, 41 without aw-window data)
                5 x Discord -> Google Chrome
                3 x Google Chrome -> Discord
                2 x Zoom -> Discord

Screenshots:
  last kept     2026-11-18 10:09 (45s ago), Cursor, screenshots/2026-11-18/6f1c2a52-8d0e-4b7a-9c3e-1a2b3c4d5e11.jpg
  today         402 kept, 377 duplicate, 6 secure-field, 0 no-permission, 1 failed
  all stored    6,904 kept, 7,311 duplicate, 85 secure-field, 12 no-permission, 9 failed
  disk          1.1 GB in total, 71.2 MB today (from kept records)

Rows:
  ...

Backups:
  latest        2026-11-20, taken 2026-11-20 08:14 (11h 13m ago), 18.8 MB
  daily         7 kept (the newest 7), oldest 2026-11-14
  pre-update    1 kept, newest taken 2026-11-19 16:02
  integrity     each passed SQLite's integrity check before it was kept
  folder        .../ComputerHistory/backups

Stable install:
  this run      stable
  current       572c48b, installed 2026-11-20 17:22 (2h 5m ago)
  previous      1f2e3d4, installed 2026-11-19 16:02 (1d 3h ago)
  agent         built from 1f2e3d4, installed 2026-11-20 17:25 (2h 2m ago)
                fell back 572c48b -> 1f2e3d4, 2026-11-20 17:25 (2h 2m ago): the new capture agent recorded nothing in 120s while you were active
  last update   updated 1f2e3d4 -> 572c48b, 2026-11-20 17:22 (2h 5m ago)

Stable install's LaunchAgents:
  backend          loaded, running (pid 4242)  io.github.thewisepup.computer-history.ingest
  backup           loaded, not running  io.github.thewisepup.computer-history.backup
  watchdog         loaded, not running  io.github.thewisepup.computer-history.watchdog
  activitywatch    loaded, not running  io.github.thewisepup.computer-history.activitywatch
  capture agent    loaded, running (pid 812)  io.github.thewisepup.computer-history.agent

Stable watchdog:
  last run       2026-11-20 19:27 (30s ago)
  capture agent  PROBLEM: silent while you were active, last seen 2026-11-20 19:21 (6m 30s ago), notified 30s ago
  ActivityWatch  ok: recording, last seen 2026-11-20 19:27 (30s ago)
  backend        ok: recording, last seen 2026-11-20 19:27 (30s ago)
```

Read-only: it never creates, migrates or writes, never changes the spool, and
never notifies. Everything down to `Backups:` is the given database's own; the
three `Stable` sections describe the stable install whichever profile runs.
`Ingest:`, `ActivityWatch:` and the capture agent's `alive` take the
watchdog's verdicts by its thresholds. Gaps are unobserved time, never assumed
idle; where aw-afk has no data the stretch *cannot be judged*.
`docs/DESIGN.md` §8.7 has how each line is judged. While ingest
cycles fail, status opens with a banner (real output, seven cycles into a
renamed `ingest_progress`):

```
!! ingest is FAILING since 2026-11-20 16:13 (7 cycles): aw-afk: no such table: ingest_progress

Database:      .../history.db (112.0 KB + 16.1 KB WAL, schema v5)
ActivityWatch: yes (http://127.0.0.1:50057/api/0; sources: aw-afk, aw-web, aw-window)
Ingest:        FAILING since 2026-11-20 16:13 (7 cycles), last cycle 2026-11-20 16:19 (15s ago)
  last success  2026-11-20 16:12 (7m 15s ago)
```

Before the agent has stored anything, or with no screenshot records, its
section is one line:

```
Capture agent: has not reported yet (no ax-text records stored)
  spool         3 finished files waiting (oldest 2m 30s), 0 in unreadable/  (.../ComputerHistory/spool)
Screenshots: none stored yet (no screenshot records)
```

## backfill — one-time history import

```bash
computer-history backfill --dry-run           # show the plan, write nothing
computer-history backfill                     # run it
computer-history backfill --start 2026-11-01  # override where it starts
```

```
Backfilling http://127.0.0.1:5600/api/0 into .../history.db (7d chunks)
  aw-window (1 bucket): [2026-11-12 00:00, 2026-11-18 10:10) up to its settled-until time 2026-11-18 10:10, 1 chunk
  ...
  aw-window done in 2s: inserted 3,451, skipped 0, held back 1
  progress set: settled until 2026-11-18 10:05; `computer-history ingest` continues from there without re-reading history
```

Imports existing ActivityWatch history in 7-day chunks, oldest first, one
commit each. Safe to re-run; an interrupted run resumes by re-running. A
source with no ingest progress gets it in the last chunk's commit (only if the
range covers all its history); existing progress is never moved.

## rebuild-signals — regenerate the derived layer

```bash
computer-history rebuild-signals
computer-history rebuild-signals --allow-shrink   # a mapping change drops rows on purpose
```

```
Rebuilt signals in .../history.db from stored observations
  signals before        5,960
  signals after         5,960
  skipped                   0  (malformed payloads)
```

Wipes `signals` and re-projects every stored observation through its source
adapter's projector. Needed only after changing a projector
(`activitywatch/normalize.py`, `capture_spool/normalize.py`) or `text.py`. It
aborts and rolls back when too many rows fail to project, when the result
would shrink suspiciously, or when observations come from a source this
version has no adapter for:

```
rebuild-signals aborted: no source adapter projects 'screenshot', the source of 12 stored observations (first id: 7); rolled back, signals unchanged
  this computer-history has no adapter for that source; rebuild with the version that ingested it
```

## dev build-db — a database of synthetic history

```bash
computer-history dev build-db --persona developer --scenario typical --tier day --seed 1 --out /tmp/dev
computer-history status --db-path /tmp/dev/history.db   # its spool, /tmp/dev/spool, stays empty
```

```
Dataset persona=developer, scenario=typical, tier=day, seed=1, start=2026-01-05, timezone=America/Los_Angeles, heavy=1.0
  built: ~/Library/Caches/ComputerHistory/datasets/69b4a3a750a56e1dd6c2543276a92ee8
  database   /tmp/dev/history.db
  manifest   /tmp/dev/manifest.json
  rendered-spool/ /tmp/dev/rendered-spool
```

Builds a synthetic dataset through the real backfill and poll, or reuses the
one in the dataset cache (`reused from the cache`), and copies it into
`--out`: the database, the manifest of true answers and the rendered source
files. `--persona`, `--scenario`, `--tier` and `--seed` are required; `--start`,
`--timezone` and `--heavy` (a heavier user, `--heavy 3` for another factor) are
optional. The same inputs always give the same database contents.

It refuses, with exit code 1, to write into a live folder (after resolving
symlinks and ignoring case), and an `--out` that already holds a file it would
write (`... already holds history.db, manifest.json; pass --force to replace
them`). The cache is `$COMPUTER_HISTORY_DATASET_CACHE`, else
`~/Library/Caches/ComputerHistory/datasets/` on macOS (`$XDG_CACHE_HOME`, or
`~/.cache`, then `computer-history/datasets/` elsewhere), shared by every
worktree and
keyed by the inputs and the code, so any change to ingest rebuilds it. Delete
it at any time.

## dev snapshot — the live database, copied into dev

```bash
computer-history dev snapshot           # into the dev folder's history.db
computer-history dev snapshot --force   # replace the copy already there
computer-history status                 # dev now reads the copy
```

```
$ computer-history dev snapshot
Profile dev (branch 104-dev-snapshot at f3eb7a0), database ~/Library/Application Support/ComputerHistory-dev/history.db
Snapshot of the live database ~/Library/Application Support/ComputerHistory/history.db
  copied to ~/Library/Application Support/ComputerHistory-dev/history.db
  schema v5, 153.5 MB, integrity ok
$ computer-history dev snapshot
Profile dev (branch 104-dev-snapshot at f3eb7a0), database ~/Library/Application Support/ComputerHistory-dev/history.db
dev snapshot refused: ~/Library/Application Support/ComputerHistory-dev already holds history.db; pass --force to replace it
```

The one sanctioned read of live data from dev. It copies only `history.db` in
the live folder, read-only through SQLite's online backup (the stable backend
keeps ingesting), checks the copy's integrity and puts it in dev's database
(`$COMPUTER_HISTORY_DB` or `--db-path` names the target, never the source).
The target is refused inside the live folder from any profile. `--force`
refuses while another process has the target open. It copies the database
only, so screenshot paths in the copy point at files dev doesn't have, and it
never migrates: `ingest` does.

## dev perf — the performance gate

```bash
computer-history dev perf                      # day and month, against the committed baseline
computer-history dev perf --update-baselines   # record a deliberate change of cost
computer-history dev perf --dataset day --dataset year   # a nightly dataset (also: heavy-year)
computer-history dev perf --counters costs.json          # also write what an update would write
```

```
SQLite 3.54.1, 54 compile options:
  ATOMIC_INTRINSICS=1 COMPILER=clang-21.0.0 DEFAULT_AUTOVACUUM ...
Baseline: .../computer_history/synthetic/perf_baselines/sqlite-3.54.1.json

operation        dataset      statements      VM steps    pages
ingest           day               8,861       281,335    2,225
rebuild-signals  day               3,619       232,084    2,225
status-reads     day                  15        78,718        -
capture-health   day                   6        71,743        -
ingest           month           251,848     8,087,820   83,286
...
expected to fail, status-reads on month: 340,350 VM steps, over the 45,922 the day dataset allows
expected to fail, capture-health on month: 481,452 VM steps, over the 143,486 the day dataset allows

Performance gate passed.
```

Runs each operation (`ingest` into an empty database, `rebuild-signals`, the
store reads `status` makes, and the capture agent's health) on the developer
persona's `messy` datasets from the dataset cache, once untimed and once with
SQLite's work counted: statements run, VM instructions, full table scans in
the query plans of the reads it ran, and the pages of a database it writes.
It compares those with the baseline for the SQLite it runs on,
`computer_history/synthetic/perf_baselines/sqlite-<version>.json`, and
exits 1 on any difference: statements, scans and pages exactly, VM steps past
2%, cheaper ones too, so an improvement is locked in by rerunning with
`--update-baselines` and saying why in the pull request. A scan fails unless
its statement is on the gate's short allowlist (the row counts and source
totals `status` prints, and rebuild's pass over every observation). The
scaling check fails when a windowed read on month costs more than twice its
day cost, or another operation grows half again faster than the events; the
two known failures are tracked in #84. Each failure names the operation,
counter, before and after, and the statements that changed most:

```
ingest on day: statements 8,861 -> 12,535 (+41.5%), worse than the baseline
  statements that changed most:
    0 -> 3,674 runs, 0 -> 29,392 VM steps: SELECT id FROM observations WHERE id = ?
```

The scaling check needs `day` beside a larger dataset and says so when it is
missing. A dataset with no entry reports `no baseline yet` until it is recorded
with `--update-baselines`.

There is one baseline file per SQLite version, because VM steps differ between
versions: CI's 3.45.1 runs one more instruction per inserted row than 3.54.1,
so `ingest` costs 2.6% more there, past the tolerance. Statements, scans and
pages match exactly across both. A SQLite with no file of its own is compared
with the newest version's file, and the run says so. `--update-baselines`
writes only the running SQLite's file, so a deliberate change of cost updates
two files: yours, and CI's from the `perf-counters` artifact of the failed CI
run, whose `perf-counters.json` is the file an update would write:

```bash
gh run download <run-id> -n perf-counters -D /tmp/perf
cp /tmp/perf/perf-counters.json computer_history/synthetic/perf_baselines/sqlite-<CI version>.json
```

The nightly run measures day, year and heavy-year on `ubuntu-24.04` in about
two hours; heavy-year peaks near 12 GB of memory, and at 17 GB it is built
afresh each night rather than cached.

`pytest -m perf` runs the same gate; the default `pytest` leaves it out.

## dev bench — the wall-clock benchmark

```bash
computer-history dev bench                     # day and month, against this machine's last timings
computer-history dev bench --dataset year      # any dataset dev perf takes
computer-history dev bench --update-baseline   # record these timings as the machine's new ones
```

Real output, on an M5 Max, after a first run recorded the baseline:

```
Median of 5 runs, against this machine's baseline ~/Library/Caches/ComputerHistory/datasets/bench_baseline.json

operation        dataset         median   baseline    change
ingest           day            0.128 s    0.130 s     -1.4%
rebuild-signals  day            0.041 s    0.041 s     -0.2%
status-reads     day            0.002 s    0.002 s     -0.1%
capture-health   day            0.010 s    0.010 s     -0.3%
ingest           month          4.816 s    4.837 s     -0.4%
rebuild-signals  month          1.657 s    1.681 s     -1.4%
status-reads     month          0.040 s    0.040 s     +0.1%
capture-health   month          0.040 s    0.040 s     +0.5%

Nothing more than 25% slower than this machine's baseline, of 8.
```

Times each operation `dev perf` counts five times, without the cost meter,
each run started afresh, and reports the median. It catches Python-side
slowdowns the counters can't see. The baseline is `bench_baseline.json` in the
dataset cache folder, so it belongs to this machine: a timing it lacks is
recorded (`recorded`), and one more than 25% slower is marked `SLOWER`. A run
with no baseline at all says so (`No baseline on this machine yet: these
medians become it, nothing compared.`) rather than that nothing got slower,
and `--update-baseline` says `Baseline rewritten from these medians`.
`--update-baselines` is accepted for `--update-baseline`, as `dev perf` spells
it. It exits 0 either way; only a run that can't happen at all exits 1. The nightly
CI run keeps no baseline, since each night lands on a different VM, so there it
reports medians only.

## logs — what the commands did

```bash
computer-history logs --since 1h               # 30m, 2h, 1d, or an ISO date/datetime
computer-history logs --level error            # this level and above
computer-history logs --run d5f6018a           # one run: one command invocation
computer-history logs --logger sources         # a logger and those below it
computer-history logs --level error --json     # the raw JSON lines
```

Every command logs to stderr as text and to `computer-history.jsonl` in
`$COMPUTER_HISTORY_LOG_DIR`, else `~/Library/Logs/computer-history/` for
stable and `~/Library/Logs/computer-history-dev/` for dev; `logs` reads its
own profile's folder, rotated files included, oldest first. Each record
carries `ts` (UTC), `level`, `logger`, `msg`, `run` (an id per invocation),
`cmd`, its fields, and `exc` for a traceback. Text output shows only plain
fields; nested ones (`streams`, `failures`) are in the JSON. Real output:

```
2026-11-20 17:16:32 ERROR   sources.cycle_report [ingest --watch d5f6018a]  cycle failed: ingest failed on aw-afk: database error: no such table: ingest_progress  duration_ms=2 retry_s=60 streak=1
  | Traceback (most recent call last):
  |   File ".../computer_history/sources/runner.py", line 85, in poll
  |     _poll_stream(conn, source, stream, project, outcomes, now=at)
  ...
  | sqlite3.OperationalError: no such table: ingest_progress
```

A command that crashes logs `command crashed` as CRITICAL with its traceback
and exits 1. With no records yet, `logs` says `no log records yet in
<folder>`.

## When the database can't be used

Every command opens the store the same way and refuses, with exit code 1 and
no traceback, when the database is:

- **newer** than this CLI (`cannot use ...: schema v6 is newer than this CLI
  understands (v5); upgrade computer-history`). Nothing is read or written.
- **busy** while opening for write, e.g. another process is migrating
  (`cannot open ...: database is locked` plus a try-again hint).
- **not a database** (`cannot open ...: file is not a database`).

An **outdated** schema is migrated by `ingest`, `backfill` and
`rebuild-signals`. `status` and `backfill --dry-run` never migrate: status
prints `note: this CLI uses schema v5; computer-history ingest will migrate
the database` and stops there, and a dry run refuses. A **missing** database
is created by `ingest` and `backfill` (only once planning succeeds), shown as
"not created yet" by `status`, and refused by `rebuild-signals`.

## Global flags

```bash
computer-history --db-path /tmp/scratch.db ingest   # or $COMPUTER_HISTORY_DB
computer-history status --aw-url http://127.0.0.1:5666/api/0
computer-history ingest --spool-path /tmp/spool     # or $COMPUTER_HISTORY_SPOOL
computer-history --log-level debug ingest           # or $COMPUTER_HISTORY_LOG_LEVEL
```

Without `--log-level` the JSON log gets INFO and stderr WARNING, since each
command prints its own report; `ingest --watch` logs INFO to stderr too. At
DEBUG, stderr shows tracebacks. Without `--spool-path` the spool is the
`spool/` folder beside the database, so a scratch database never collects the
real spool. Without `--db-path` the database is the profile's (see Profiles
above).
