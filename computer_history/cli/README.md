# computer-history CLI

The command line for the local activity store: it ingests settled
ActivityWatch events and the capture agent's spool into SQLite and reports on
what is stored. All business logic lives in `sources/` and `store/`; this
package only parses arguments, builds the clients, source adapters and
connection, calls one function, and formats the result.

```
app.py         parser + dispatch: one entry per command, the profile's log
  |              folder, the install lock around the commands that change
  |              the stable install, and --spool-reads
  +-- ingest.py    one poll, or the --watch loop, through the ingest runner
  |                (ActivityWatch and the capture spool in one loop), with
  |                the ingest health file and the failure streak's notification
  |                after each cycle, and spool deletion held until a cycle
  |                completes while update asks for it
  +-- status.py    the status report (`computer_history/status/`) formatted: the
  |                given database's ingest, freshness, coverage gaps, capture
  |                agent, screenshots, row counts and backups, then the stable
  |                install, its agent's build, its last update, its LaunchAgents and the
  |                watchdog's findings
  +-- rebuild.py   rebuild-signals
  +-- backfill.py  plan, then ingest history chunk by chunk through the runner
  +-- install.py   install and uninstall the stable install, through the host adapter
  +-- agent_guard.py  check-agent-install: whether this checkout's capture agent
  |                may be installed by hand, the unmet conditions and their fixes
  +-- update.py    update (to the newest passing commit, falling back on its own)
  |                and rollback (to the previous version, if it opens the database)
  +-- backup.py    backup (the day's backup, seven days kept) and restore (a backup
  |                put in place, the stable backend, watchdog and daily backup
  |                stopped and started around it)
  +-- watchdog.py  one watchdog run: check, notify, reopen ActivityWatch, and its
  |                findings as lines (formatting.py formats them, for status too)
  +-- logs.py      the JSON log's records, filtered, as text or raw lines
  +-- dev.py       dev build-db: a database of synthetic history from the dataset cache;
  |                dev snapshot: the live database copied into the dev folder;
  |                dev perf: the performance gate against the committed baseline
        |
db.py and sources.py (unusable database / source messages, and the ActivityWatch
timeout status and the watchdog share),
profile.py (the first line: profile, version or checkout, database),
formatting.py (durations, times, sizes, and the clock every command reads)
```

Run it as `.venv/bin/computer-history`, or bare `computer-history` with the
venv activated (or aliased).

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
reads ActivityWatch and an empty dev spool.

Every command's first line names the profile, the version (stable) or the
checkout's branch and commit (dev), and what the command uses: the database
for `ingest`, `status`, `rebuild-signals` and `backfill`, the database it
copies into for `dev snapshot`, the `--out` folder for `dev build-db`, and
nothing more for `dev perf`. Those two dev tools (`dev build-db` and
`dev perf`) open neither
the database nor the spool, so they are never refused; `dev snapshot` is the
one command that reads live data from dev (see its section below). Real
output, home shortened to `~`:

```
$ computer-history status
Profile dev (branch 103-dev-profile-data-folder at f8ea2fb), database ~/Library/Application Support/ComputerHistory-dev/history.db
...
$ computer-history --db-path ~/Library/Application\ Support/ComputerHistory/history.db ingest
Profile dev (branch 103-dev-profile-data-folder at f8ea2fb), database refused
refused: ~/Library/Application Support/ComputerHistory/history.db is in the live data folder ~/Library/Application Support/ComputerHistory. This run is dev (its code is a checkout or worktree, not the stable install), and dev never uses live data. Leave --db-path and $COMPUTER_HISTORY_DB unset to use ~/Library/Application Support/ComputerHistory-dev/history.db, or run the stable install's computer-history.
```

Stable prints `Profile stable (version 1a2b3c4), database ~/Library/Application Support/ComputerHistory/history.db`.
Dev reads the branch and commit from the checkout's `.git` folder (or a
worktree's `.git` file) without running git: `(branch main, no commits yet)`
before the first commit, `(detached at <commit>)` on a detached HEAD,
`(an installed copy, not a checkout)` for a copy installed into a venv's
`site-packages`, and `(not a git checkout)` otherwise.

```
$ computer-history dev build-db --persona developer --scenario typical --tier day --seed 1 --out /tmp/dev
Profile dev (branch 103-dev-profile-data-folder at 1e42a9e), output /tmp/dev
```

## install and uninstall — the stable install

```bash
brew install uv                      # once: install builds with uv
.venv/bin/computer-history install   # from a checkout; safe to re-run
computer-history uninstall           # LaunchAgents, versions and the link; never the data
```

`install` sets up the stable install in the live folder and starts the
backend at login from it. With no current version it finds the newest `main`
commit that passed the **release gate** (every one of `lint`, `unit`, `data`,
`poc`, `secrets`, `macos-capture-agent-tests` and `macos-capture-agent-e2e`
completed successfully on its push run; `typecheck` and `perf` are ignored),
through GitHub's public API (no token needed; `$GITHUB_TOKEN` is sent when
set, which lifts the 60-requests-an-hour limit a walk of up to 21 requests
shares), and builds it with `uv` on a
uv-managed Python 3.12 into `versions/<short commit>/`, with its frozen
package list in `packages.txt` and the `installed` marker written last. Then
it points `current` at it, links `~/.local/bin/computer-history` to
`current/venv/bin/computer-history`, boots out and deletes the stopgap
`io.github.thewisepup.computer-history.backend` LaunchAgent (asked of launchd
by label, so a stopgap whose plist was deleted is found too), and loads the
backend LaunchAgent `io.github.thewisepup.computer-history.ingest`
(`computer-history ingest --watch` from `current`, started at login,
restarted by launchd when it exits, at most every 30s; log in
`~/Library/Logs/computer-history/backend.log`), the daily backup
LaunchAgent `io.github.thewisepup.computer-history.backup` (`computer-history
backup` at 03:00 and at login; see "backup and restore" below), the watchdog
LaunchAgent `io.github.thewisepup.computer-history.watchdog` (`computer-history
watchdog` from `current`, at load and then every 60s; only its stderr goes to
`watchdog.log`) and `io.github.thewisepup.computer-history.activitywatch`,
which runs `/usr/bin/open -g -b net.activitywatch.ActivityWatch` once at login
so ActivityWatch starts with the session. The database, spool,
screenshots and agent config stay where they are.

Run again with a current version, it skips GitHub and `uv` and repairs the
rest: the link, the plists (each rewritten, its running job booted out and
waited for, up to 5s, and then loaded again, retried twice while launchd is
still busy with the old copy) and the stopgap. Moving
stable to a newer commit is `update`'s job. Offline, without `uv`, or with no
passing commit among the newest 20, or when a folder or file cannot be
written, it fails with exit code 1 and changes nothing: whatever it created
is removed again. A GitHub failure names the call (`could not list main's
newest commits from GitHub: ...`), and a used-up rate limit says when it
resets. A file at `~/.local/bin/computer-history` that is not the install's
own link is refused, never replaced.

Real output through the CLI with the test suite's fake host adapter, in a
temporary home (home shortened to `~`, live folder to `.../ComputerHistory`):

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
$ .venv/bin/computer-history install
Profile dev (branch 106-install-stable at f3eb7a0), stable install ~/Library/Application Support/ComputerHistory
Version 572c48b is already installed and current
  current       .../ComputerHistory/current -> .../ComputerHistory/versions/572c48b
  PATH link     ~/.local/bin/computer-history -> .../ComputerHistory/current/venv/bin/computer-history
  LaunchAgent   io.github.thewisepup.computer-history.ingest loaded: computer-history ingest --watch, restarted by launchd at most every 30s
  LaunchAgent   io.github.thewisepup.computer-history.backup loaded: computer-history backup, daily at 03:00 and at login
  LaunchAgent   io.github.thewisepup.computer-history.watchdog loaded: computer-history watchdog, every 60s
  LaunchAgent   io.github.thewisepup.computer-history.activitywatch loaded: /usr/bin/open -g -b net.activitywatch.ActivityWatch, once at login
$ computer-history uninstall
Profile dev (branch 106-install-stable at f3eb7a0), stable install ~/Library/Application Support/ComputerHistory
  removed       ~/Library/LaunchAgents/io.github.thewisepup.computer-history.ingest.plist
  removed       ~/Library/LaunchAgents/io.github.thewisepup.computer-history.backup.plist
  removed       ~/Library/LaunchAgents/io.github.thewisepup.computer-history.watchdog.plist
  removed       ~/Library/LaunchAgents/io.github.thewisepup.computer-history.activitywatch.plist
  removed       ~/.local/bin/computer-history
  removed       .../ComputerHistory/current
  removed       .../ComputerHistory/versions
Kept the data in ~/Library/Application Support/ComputerHistory
```

When `~/.local/bin` is not on `PATH`, `install` ends with a note saying so.
A failure says whether anything changed:

```
install failed: could not read thewisepup/computer-history's checks from GitHub: <urlopen error ...> (nothing was changed)
install failed: uv is not installed (install it with `brew install uv`) (nothing was changed)
```

`uninstall` removes the link only when it is the install's own, and keeps the
logs and the backups. Both commands reach launchctl, GitHub and `uv` only through the host
adapter (`computer_history/host/`), so tests run them against a fake.

## --spool-reads — what this code reads from the spool

```bash
computer-history --spool-reads
```

Prints the spool version and record kinds this code's backend reads, as one
JSON line, and exits before any command runs (no profile line, no database).
`install` and `update` ask it of every version they build and keep the answer
as that version's `spool-reads.json`. Real output:

```
{"spool_version": 1, "kinds": ["capture", "excluded", "paused", "resumed", "slept", "woke", "screenshot"]}
```

## update and rollback — moving the stable install

```bash
computer-history update              # to the newest main commit that passed the release gate
computer-history update --wait 1800  # wait up to 30 minutes for the first cycle (default 600s)
computer-history rollback            # back to the previous version; no network
```

`update` finds the newest `main` commit the release gate passes, as `install`
does. It only moves forward: when that commit is `current`, or older than
`current` on `main` (say `current`'s checks were re-run and cancelled since
it was installed), it says `Already up to date` and changes nothing.
Otherwise it first readies the capture agent, then builds the commit beside
the current version into `versions/<short commit>/` and smokes it by asking
the built command what it reads (`--spool-reads`, kept as `spool-reads.json`);
a failed build or smoke removes that folder and changes nothing, as does being
offline.

The capture agent counts as changed when the git tree hash of
`capture-agent/` at the new commit differs from the one at the commit the
installed agent was built from, read from GitHub. That commit is
`installed-agent.json` in the live folder; when it is missing, unreadable or
no app sits at `~/Applications/ComputerHistoryAgent.app`, the agent counts as
changed. Changed, `update` checks for Swift and the `Computer History Code
Signing` identity before building anything, then builds and signs the agent
from a fresh export of the commit with that commit's own
`capture-agent/scripts/build.sh` into the new version's
`ComputerHistoryAgent.app/`, noting the commit in `agent-commit.txt`.
Unchanged, it copies the installed agent's app there with its signature: from
the old version's folder when that holds it, else from the fixed path. A
version folder still on disk that already holds an app (an update back to the
version a rollback left) keeps it. A missing toolchain, an unreadable tree
hash, a failed build or signing, or Ctrl-C during the build removes the new
folder and ends with `nothing was changed`, the backend still running. The
app at the fixed path is touched only after the backend's first ok cycle (below).

Then it boots out the backend, takes the pre-update backup
(`backups/pre-update/history-<local time>-<old version>.db`, the same SQLite
online backup and integrity check as the daily one), places the spool hold
(`spool-deletion-held` beside the database), points `previous` at the old
version and `current` at the new one, and loads the backend again. A failure
after the backup and before the switch removes the backup and the built
folder and starts the backend again, so `nothing was changed` holds. Only the
backend restarts: the daily backup, the watchdog and the ActivityWatch login
agent keep running (a fallback that restores the backup stops and starts the
daily backup and the watchdog around it, as `restore` does).

While the hold exists, every ingest (the backend's `--watch` and a one-shot
`ingest` alike) stores spool files but deletes or sets aside none. The
backend's first cycle with no failure removes the hold; the next cycle reads
the kept files again (all `skipped`, since `(source, source_id)` is unique)
and deletes them as usual. `update` waits up to `--wait` seconds (600 by
default; **a long migration needs a longer wait**; a deadline on the
monotonic clock) for a cycle in `ingest-health.json` newer than the restart:

- **ok**: it removes the hold, swaps the capture agent when it changed (below),
  deletes the version `previous` pointed at before (one previous version is
  kept), logs `updated` with the agent's outcome and exits 0 (3 when the
  agent fell back).
- **failed only because a source was unavailable** (ActivityWatch down, the
  file's `sources_unavailable`): not a reason to fall back; it keeps
  waiting for a cycle that succeeds or fails for another reason. If the
  sources stay down for the whole wait, it falls back with that reason.
- **failed, crashed, none in time or interrupted** (a crash is launchd
  reporting a different process, or none, after it had one; Ctrl-C or a
  SIGTERM during the switch or the wait counts as interrupted): it boots the
  new backend out, points `current` and then `previous` back, restores the
  pre-update backup only when the database's schema version is no longer the
  backup's (through `restore`, so the replaced database is set aside, never
  deleted), then removes the hold (it keeps it, with a warning, when the new
  backend could not be confirmed stopped; the next ok cycle removes it), loads
  the backend on the old version (which reads the kept
  spool files again harmlessly), posts a notification (`Update to 9f0e1d2
  fell back: the backend crashed before its first ingest cycle; back on
  8d23e3a.`), logs `fell back` with the reason and exits 1 (130 when
  interrupted). It deletes the new version's folder only when the new backend
  was confirmed stopped and both pointers went back; otherwise it keeps the
  folder so whatever still names it runs. Each step that fails is printed as
  a `warning:` line and the rest still run. A Ctrl-C or SIGTERM during a
  fallback is noted and the fallback runs to its end, then `update` exits 130.

A changed capture agent is swapped only after that ok cycle, so a new record
kind always meets a backend that reads it; a backend fallback never touches
the agent. First the app at the fixed path is copied into the old version's
folder when that folder doesn't already carry it (its `agent-commit.txt`
naming the installed agent's commit), so there is always an app to put back.
Then the new version's app is installed over
`~/Applications/ComputerHistoryAgent.app` and registered, and
`installed-agent.json` is rewritten. The swap time is when the host first
registered the new app, once the old one was unregistered, so a record the
new agent writes while launchd is still being asked about it counts.
`update` then polls every 2 seconds for a record, stored or still in the
spool, captured at or after the swap, counting only time aw-afk shows you
active:

| What it sees | Agent outcome | Exit |
|---|---|---|
| a record from the new agent, of any kind (`paused` too) | `updated and verified` | 0 |
| the newest record is a `paused` one from before the swap | `installed, not verified: capture is paused` | 0 |
| ActivityWatch unreachable, or without an aw-afk bucket | `installed, not verified: ActivityWatch could not say whether you were active` | 0 |
| aw-afk's stored spans can't be read | `installed, not verified: your activity since the swap could not be read: ...` | 0 |
| under 120 active seconds within 600 wall-clock seconds | `installed, not verified: you were not active for 120s within the 600s wait` | 0 |
| 120 active seconds, no record, and the database can't be read (its schema is newer than the version running `update` reads, after a migration) | `installed, not verified: ..., but the database's schema is newer than this update reads, so only the spool was checked` | 0 |
| 120 active seconds, no record | `fell back` | 3 |
| the new agent could not be registered or started | `fell back`, at once | 3 |
| the installed app could not be copied into the old version's folder, or the installed agent could not be unregistered | `not swapped: 8d23e3a's capture agent keeps running`, at once, with the cause as a `warning:` line; no fallback line, no notification | 0 |
| Ctrl-C or SIGTERM during the wait | `fell back` | 130 |

The copy into the old version's folder is staged beside it and renamed into
place, so a failed copy leaves that folder's app as it was. An agent fallback
installs the old version's app over the fixed path again,
rewrites `installed-agent.json` (removes it when that app's commit is
unknown or it could not be put back, so the next update rebuilds the agent),
moves the failed build and its note to `ComputerHistoryAgent.fell-back.app`
and `agent-commit.fell-back.txt` in the new version's folder and copies the
restored app and its note into the usual slot, logs `agent fell back`, and
posts a notification (`The capture agent from 9f0e1d2 fell back to
8d23e3a's: the new capture agent recorded nothing in 120s while you were
active. Its build is kept at .../versions/9f0e1d2/ComputerHistoryAgent.fell-back.app.`);
the update's output names it too (`kept          .../ComputerHistoryAgent.fell-back.app
(the build that fell back)`). When the new agent can't be unregistered, the
fallback says it stays. Each step that fails is a `warning:` line and
the rest still run. The new backend, the pointers and the database stay; the
failed build stays aside in the new version's folder, where you can inspect
or launch it by hand, until that folder is pruned. Because the next update compares against
the installed agent's commit, it tries the agent again even when its source
didn't change since. The record reads use the live database and the spool
beside it, where launchd's agent and backend write and read (never
`$COMPUTER_HISTORY_SPOOL`), and aw-afk at `--aw-url` (default
`http://127.0.0.1:5600/api/0`).

Ctrl-C or SIGTERM before the switch (during either build, the backend's stop,
the backup or the hold) undoes what `update` did, starts the backend again and
exits 130: `update interrupted before switching versions (nothing was
changed)`.

`rollback` points `current` at the previous version, then `previous` at the
one it left, and restarts the backend; it needs no network and no build, and
running it twice returns to where it started. If `previous` cannot be
pointed, it points `current` back, so both versions stay referenced. It does
not restore a backup. When the database's schema is newer than the previous
version can open (the newest migration in that version's own package), it
refuses and changes nothing, naming the pre-update backup to restore first
(illustrative):

```
rollback failed: the database is at schema v6, newer than version 572c48b can open (v5); put its pre-update backup back first with `computer-history restore .../backups/pre-update/history-2026-11-20T191952-572c48b.db`, then roll back (nothing was changed)
```

With no previous version it fails and changes nothing.

`rollback` also takes the capture agent back when the previous version can't
read what the installed agent writes. What the agent writes is the
`spool-reads.json` of the version folder whose `agent-commit.txt` names the
agent's `built_from` in `installed-agent.json`; what the previous version
reads is its own `spool-reads.json`. When the previous version reads that
spool version and every kind (or carries the same build), the agent stays.
Otherwise the previous version's app is installed over
`~/Applications/ComputerHistoryAgent.app` and registered before the backend
restarts, and `installed-agent.json` is rewritten. There is no record wait:
the install only confirms launchd shows the agent running, and the watchdog
covers the rest. When either side is unknown (a version from before this
note existed, no installed-agent record) or the previous version carries no
app, it warns and leaves the agent; it never refuses over the agent. An
agent that doesn't start after the move is a warning too, and its record is
removed so the next `update` deploys it again. Output from the tests' fake
host (illustrative names):

```
$ computer-history rollback
Profile stable (version 8d23e3a), stable install .../ComputerHistory
Rolled back to version 572c48b from 8d23e3a
  previous      8d23e3a (rollback again returns to it)
  agent         moved back to 572c48b's build (572c48b does not read its heartbeat records)
  backend       restarted
$ computer-history rollback      # previous version from before spool-reads.json
Profile stable (version 8d23e3a), stable install .../ComputerHistory
Rolled back to version 572c48b from 8d23e3a
  previous      8d23e3a (rollback again returns to it)
  agent         not moved
  backend       restarted
  warning: could not tell which record kinds 572c48b reads; the capture agent was left as it is
```

`install`, `uninstall`, `update`, `rollback` and a stable `restore` take turns:
each holds an exclusive lock on the live folder while it runs, and a second
one exits 1 at once (`update refused: another install, uninstall, update,
rollback or restore is using .../ComputerHistory; run it again once that one
has finished`).

Every update, fallback, agent fallback and rollback adds a JSON line to
`update-log.jsonl` in the live folder (`{"at": ..., "action": "updated" |
"fell back" | "agent fell back" | "rolled back" | "agent rolled back", "from":
..., "to": ..., "reason": ...}`); `status` shows the last one. An `updated`
line adds `"agent"`, the capture agent's outcome (`unchanged`, `updated and
verified`, `installed, not verified`, `not swapped` or `fell back`). An agent fallback writes its `agent fell back` line (from the new
version, to the old one, with the reason) before the run's `updated` line
(illustrative):

```
{"at": "2026-11-20T19:24:31+00:00", "action": "agent fell back", "from": "9f0e1d2", "to": "8d23e3a", "reason": "the new capture agent recorded nothing in 120s while you were active"}
{"at": "2026-11-20T19:24:31+00:00", "action": "updated", "from": "8d23e3a", "to": "9f0e1d2", "reason": null, "agent": "fell back"}
```

A rollback that moves the agent writes its `agent rolled back` line (from and
to are the versions whose agent builds were swapped, the reason says what the
older one can't read) before its `rolled back` line. `status` skips lines
whose action it doesn't know, so a version reached by rollback shows the last
line it understands instead of calling the log unreadable.

Real output through the CLI with the test suite's fake host adapter scripting
check results, a clean first cycle, a crash and a failed build, in a
temporary home:

```
$ computer-history update
Profile stable (version 572c48b), stable install .../ComputerHistory
Already up to date: version 572c48b is current
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
$ computer-history update
Profile stable (version 8d23e3a), stable install .../ComputerHistory
update failed: could not build version 9f0e1d2: could not install commit 9f0e1d2: No solution found (nothing was changed)
$ computer-history update
Profile stable (version 8d23e3a), stable install .../ComputerHistory
update failed: could not list main's newest commits from GitHub: offline (nothing was changed)
$ computer-history update
Profile stable (version 8d23e3a), stable install .../ComputerHistory
update failed: cannot build the capture agent: Swift is not installed (run `xcode-select --install`) (nothing was changed)
$ computer-history update
Profile stable (version 8d23e3a), stable install .../ComputerHistory
update failed: could not build the capture agent for version 9f0e1d2: could not build and sign the capture agent at 9f0e1d2...: error: no such module 'CaptureAgent' (nothing was changed)
$ computer-history update
Profile stable (version 8d23e3a), stable install .../ComputerHistory
Already up to date: version 8d23e3a is current (the newest passing commit, 572c48b, is older than current)
$ computer-history rollback
Profile stable (version 8d23e3a), stable install .../ComputerHistory
Rolled back to version 572c48b from 8d23e3a
  previous      8d23e3a (rollback again returns to it)
  agent         not moved (572c48b reads every record kind it writes)
  backend       restarted
```

A failed first cycle says why, from `ingest-health.json` (`the backend's first
ingest cycle failed: ...`), and a schema change reads `restored <backup> (the
new version changed the schema)`.

## check-agent-install — guarding the capture agent's hand install

```bash
capture-agent/scripts/install.sh            # runs the guard first; a refusal stops it before the build
capture-agent/scripts/install.sh --force    # passes --force on: install anyway, listing what was skipped
.venv/bin/computer-history check-agent-install [--force]   # the guard alone
```

The capture agent is installed by hand with its install script, which asks
this command first and holds no checks of its own. It allows the install only
when all of these hold for the checkout the command runs from (its own code's
folder, whatever the current directory; `GIT_DIR` and friends are ignored):

| Condition | Unmet when | Fix it names |
|---|---|---|
| on main | another branch, or HEAD detached | `git switch main` |
| clean working tree | `git status --porcelain` lists anything, untracked files included | commit or stash |
| HEAD is origin/main | they differ, or there is no `origin/main` (read locally; nothing is fetched) | `git pull` / `git fetch origin main` |
| capture-agent checks passed on HEAD | `macos-capture-agent-tests` or `macos-capture-agent-e2e`, the release gate's capture-agent checks, failed, was cancelled, is still running or never ran | wait for CI if running; re-run CI or check the job name if it never ran; else fix and re-run |
| stable backend at HEAD or newer | there is no stable install, or `current` is not HEAD and is a version older than HEAD among `main`'s newest 20 commits (the release gate's walk, never local ancestry), or HEAD is not among them | `computer-history install` / `update` / `git pull` |

Every unmet condition is listed at once with its fix, on stderr, and the exit
code is 1. GitHub out of reach is a refusal too, with the host's error, since
an unverified commit needs an explicit `--force`. `--force` exits 0 and lists
each condition it skipped. A checkout git can't read refuses (or, with
`--force`, says the guard could not run and passes). The command only reads:
git, GitHub, and the stable install's `current` pointer, which a dev checkout
may read; it opens no database or spool and takes no install lock.

Real output through the CLI with the test suite's fake host adapter (live
folder shortened to `.../ComputerHistory`):

```
$ .venv/bin/computer-history check-agent-install
Profile dev (branch main at 572c48b), stable install .../ComputerHistory
Agent install refused: 3 unmet conditions for HEAD 572c48b (pass --force to install anyway)
  clean working tree: the working tree has uncommitted changes; commit or stash them
  capture-agent checks passed on HEAD: macos-capture-agent-e2e running; wait for CI to finish on it
  stable backend at HEAD or newer: the stable backend is version 5e26ac9, older than HEAD 572c48b; move it forward first: computer-history update
```

Real output from a feature-branch checkout with real git and GitHub, in a
temporary home with no stable install:

```
$ .venv/bin/computer-history check-agent-install --force
Profile dev (branch 134-agent-install-guard at 4de83b8), stable install .../ComputerHistory
Agent install allowed by --force, skipping 3 unmet conditions for HEAD 4de83b8:
  on main: the checkout is on 134-agent-install-guard; switch: git switch main
  clean working tree: the working tree has uncommitted changes; commit or stash them
  stable backend at HEAD or newer: there is no stable install; set it up first: computer-history install
```

With every condition met it prints `Agent install allowed: every condition
holds for HEAD 572c48b` and exits 0.

## backup and restore — the daily backup and putting one back

```bash
computer-history backup                    # today's backup, unless it is taken already
computer-history restore 2026-11-19        # put that day's backup in the database's place
computer-history restore <backup file>     # anything not written YYYY-MM-DD is a file path
```

`backup` copies the database with SQLite's online backup, so the backend
keeps writing while it runs, into `backups/daily/history-<day>.db` beside the
database (the live folder's `backups/` for stable, the dev folder's for dev).
The copy holds what was committed when it started and must pass
`PRAGMA integrity_check` before it is kept: a copy that fails is never kept,
and the command exits 1 (`backup failed: ...`), as it does for a database
SQLite cannot read. The copy is a single file in rollback-journal mode, so
opening it leaves no `-wal` or `-shm` beside it. Then the days older than the
newest seven are removed, with any journal files beside them. A second run on
the same day keeps the day's first backup; a journal file or a file that is
not a database in its place is removed and the backup taken. With no
database yet it takes nothing and exits 0. Only the database is backed up,
never the spool or the screenshots.

`install` loads a LaunchAgent that runs `backup` from the stable install at
03:00 and at login (`RunAtLoad`): launchd runs a 03:00 missed while the Mac
slept when it wakes, and a Mac that was off takes the day's backup at login.
Its log is `~/Library/Logs/computer-history/backup.log`.

`update` takes its own backup before it switches versions,
into `backups/pre-update/history-<local time>-<version>.db`; the daily pruning
never removes those.

`restore <day>` puts that day's daily backup in the database's place;
`restore <file>` takes any backup file (only `YYYY-MM-DD` is read as a day,
and `2026-13-01` is refused as no day). When the target is the live
database, it first boots out the daily backup, the watchdog and then the
backend through the host adapter, each only if it is loaded, so none of their
connections makes it refuse. If a boot-out fails or launchd
still has the job after 5s, it loads the job again and stops with `nothing
was changed`. When anything else still has the database open, such as an
`ingest --watch` in a terminal, it refuses and starts the agents again.
Otherwise, holding the database's exclusive lock, it folds the WAL into the
file and moves it to `backups/set-aside/history-<local time>.db`, never
deleting it, copies the backup in (integrity checked; on any failure the
database is moved back) and loads the agents it stopped again. A backend that
was not loaded is left stopped. A restore into any other database, a dev one
or one passed by `--db-path`, never touches launchd, and with no database in
the way it sets nothing aside. To undo a wrong restore, restore the set-aside
file by path.
What was ingested after the backup was taken is only in the set-aside copy:
ActivityWatch's events are ingested again from where the backup's progress
stood, but spool files were deleted once stored, so their records are not.

Real output through the CLI with the test suite's fake host adapter, in a
temporary home (live folder shortened to `.../ComputerHistory`):

```
$ computer-history backup
Profile stable (version 572c48b), database .../ComputerHistory/history.db
Backed up .../ComputerHistory/history.db
  copied to .../ComputerHistory/backups/daily/history-2026-11-20.db
  schema v5, 92.0 KB, integrity ok
$ computer-history backup
Profile stable (version 572c48b), database .../ComputerHistory/history.db
Today's backup is already taken: .../ComputerHistory/backups/daily/history-2026-11-20.db
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

A run that takes the eighth day's backup also lists each file it removed
(`  removed   .../backups/daily/history-2026-11-12.db`).

## watchdog — is anything silent?

```bash
computer-history watchdog                       # what the watchdog LaunchAgent runs every minute
.venv/bin/computer-history watchdog --db-path /tmp/scratch/history.db --aw-url http://127.0.0.1:5666/api/0
```

One run checks three things, posts a macOS notification for each problem
(at most once an hour each) and once when a notified problem clears, saves
its findings to `watchdog.json` beside the database, and exits 0:

- **capture agent**: its newest record, stored or still in the spool, by the
  liveness `status` uses. A problem only while aw-afk shows you active;
  paused or idle is `cannot tell`.
- **ActivityWatch**: reachable, and this host's AFK and window sources each
  advancing, judged by the source's most recently advanced bucket (an old,
  empty or erroring sibling bucket is ignored). A problem whether or not you are active. When it is unreachable
  and its app (`aw-qt`) isn't running, the watchdog opens it, at most three
  times in any hour.
- **backend**: the last cycle in `ingest-health.json`, a problem only when it
  is older than the threshold while you are active: the backend is silent or
  dead. Cycles that run but fail are `ok: running, but its cycles fail
  (ingest alerts on that)`, with the last error, since `ingest --watch`'s own
  failure streak notifies of them; such a cycle clears a silent backend.

Each is silent after 5 minutes unless the agent's config file beside the
database (`agent-config.json`) says otherwise:

```json
{"watchdog": {"capture_agent_minutes": 10, "activitywatch_minutes": 5, "backend_minutes": 15}}
```

Values run from 1 to 1440 minutes; a bad one falls back to 5 and is shown as
`config problem: watchdog.backend_minutes must be a number of minutes from 1
to 1440, using 5`. Config problems and errors are shown on stdout every run
but written to stderr, which is what `watchdog.log` keeps, at most once an
hour per message. A run that finds another one still holding the lock
(`.watchdog.lock` beside the database) exits 0 without a word past the
profile line. After a sleep (or any run more than 3
minutes after the last), silence counts from that run, so waking the Mac
never notifies; until a subject has had one threshold to show it is alive, it
is `cannot tell`, which neither notifies nor clears.

Real output through the CLI with the test suite's fake host adapter and fake
ActivityWatch, one run a minute, the capture agent stopping after minute 2
(home shortened to `~`; times are the fake clock's, in local time):

```
$ computer-history watchdog          # minute 2
Profile stable (version bbbbbbb), database ~/Library/Application Support/ComputerHistory/history.db
Watchdog (silent after: capture agent 5m, ActivityWatch 5m, backend 5m)
  capture agent  ok: recording, last seen 2026-11-17 02:02 (0s ago)
  ActivityWatch  ok: recording, last seen 2026-11-17 02:02 (0s ago)
  backend        ok: recording, last seen 2026-11-17 02:02 (0s ago)
$ computer-history watchdog          # minute 8
Profile stable (version bbbbbbb), database ~/Library/Application Support/ComputerHistory/history.db
Watchdog (silent after: capture agent 5m, ActivityWatch 5m, backend 5m)
  capture agent  PROBLEM: silent while you were active, last seen 2026-11-17 02:02 (6m ago)
  ActivityWatch  ok: recording, last seen 2026-11-17 02:08 (0s ago)
  backend        ok: recording, last seen 2026-11-17 02:08 (0s ago)
  notified: The capture agent has recorded nothing for over 5 min while you were active.
```

The first run that finds it recording again prints `cleared: The capture
agent is recording again.`, and a clear resets the hourly limit, so a second
outage notifies again. Other lines a run can print: `reopened
ActivityWatch`, `did not reopen ActivityWatch: reopened 3 times in the last
hour`, and `error: could not post a notification: ...` (tried again next
run). Notifications are posted with `osascript`'s `display
notification`, through the host adapter, so macOS shows them as Script
Editor's.

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
harmless), `held back` is ActivityWatch events still growing — they land on a
later poll. Re-running always inserts 0 for data it already has. A stream
whose observations no adapter can project is reported (`error on aw-window: no
source adapter projects observations from 'aw-window'`, exit 1) while the
other streams are still ingested.

`--watch` is the long-running collector. It survives ActivityWatch outages and
locked databases, and writes one record per cycle to stderr and to the JSON log
(see [logs](#logs--what-the-commands-did)). Real output from a verification
run where `ingest_progress` was renamed away for two cycles:

```
2026-11-20 17:15:32 INFO    sources.cycle_report  cycle ok: aw-afk +0 (1 dup, 1 held); aw-web +0 (0 dup, 0 held); aw-window +0 (3 dup, 1 held); ax-text +0 (0 dup, 0 held); screenshot +0 (0 dup, 0 held)  duration_ms=12
2026-11-20 17:16:32 ERROR   sources.cycle_report  cycle failed: ingest failed on aw-afk: database error: no such table: ingest_progress  duration_ms=2 retry_s=60 streak=1  exc="sqlite3.OperationalError: no such table: ingest_progress"
2026-11-20 17:17:32 ERROR   sources.cycle_report  cycle failed: ingest failed on aw-afk: database error: no such table: ingest_progress  duration_ms=1 retry_s=60 streak=2
2026-11-20 17:18:32 INFO    sources.cycle_report  cycle ok: aw-afk +0 (1 dup, 1 held); aw-web +0 (0 dup, 0 held); aw-window +0 (3 dup, 1 held); ax-text +0 (0 dup, 0 held); screenshot +0 (0 dup, 0 held)  duration_ms=20
2026-11-20 17:18:32 INFO    sources.cycle_report  ingest recovered  failed_cycles=2 failing_since=2026-11-21T01:16:32.792900+00:00
```

The first failure of each distinct cause in a streak carries its traceback in
the JSON log, and so does the first after a restart. A one-shot `ingest`
writes the same record to the JSON log only, since it prints its own report.
After
every cycle the watch saves its ingest health to `ingest-health.json` beside
the database (a file, not a table, so a broken database cannot hide it):

```json
{
  "cycle_at": "2026-11-21T01:18:32.801132+00:00",
  "consecutive_failures": 0,
  "failing_since": null,
  "last_success_at": "2026-11-21T01:18:32.801132+00:00",
  "last_error": null,
  "alerted_at": null,
  "sources_unavailable": false
}
```

`sources_unavailable` is true when every failure of the last cycle was a source
it could not read, such as ActivityWatch down. The watchdog, `update`'s wait
for the first cycle and `status` all read this one file.

A restarted watch continues the saved streak, including when it last
notified, so a restart neither notifies again early nor misses the recovery. After 5 failed cycles in a row
it posts a macOS notification (`ingest failing for 5 cycles. Run
\`computer-history status\`.`), again at most hourly while the failures last,
and `ingest recovered.` once a cycle succeeds. They are posted through the
host adapter, like every notification, under the one title `Computer
History`; they never name captured content, and `COMPUTER_HISTORY_NOTIFY=0`
turns them off.

`ax-text` and `screenshot` are the capture agent's spool, read in the same
poll. Each stream stores its own records from each finished `*.jsonl` file in
one commit, oldest first; the file is deleted once both streams have stored
it. While `spool-deletion-held` sits beside the database (`update` places it),
every ingest keeps the files it stores, and a one-shot run ends with `spool
files kept: ...`; `--watch` removes the hold after a cycle with no failure,
and the next cycle reads the kept files again and deletes them. The agent's `open.part` and `agent.lock` are never touched. A stream's
`rejected` counts lines of its own kinds that are not usable records (failing
validation, or an unknown format version); a line whose kind cannot be read
(not JSON, or a kind this backend does not know) belongs to neither stream and
is counted in the warning when the file is set aside. Unusable lines are skipped
and logged, and the rest of the file is stored. A file with any unusable line
is moved into `spool/unreadable/` instead of being deleted, once both streams
stored its usable lines. A file one stream cannot read is left for that stream
to retry on the next poll; only a file neither stream can read is moved aside.
A file that cannot be removed is reported as `error on the spool` and not read
again until the next `ingest` run. A missing
spool folder is nothing to ingest. ActivityWatch being down does not stop the
spool, and the reverse: the other source's rows are stored, and the run exits
1. The same holds for an error nothing expects, such as a bug in one source: that
source's remaining streams are skipped this cycle, the others are read, and the
run prints the error's type alone (`error: unexpected KeyError`, then
``This is a bug: `computer-history logs --level error` shows its traceback.``)
and exits 1.

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

`Ingest:` reads the watch's `ingest-health.json` beside the database, before
the database itself. While cycles fail, status opens with a banner (real
output, seven cycles into a renamed `ingest_progress`):

```
!! ingest is FAILING since 2026-11-20 16:13 (7 cycles): aw-afk: no such table: ingest_progress

Database:      .../history.db (112.0 KB + 16.1 KB WAL, schema v5)
ActivityWatch: yes (http://127.0.0.1:50057/api/0; sources: aw-afk, aw-web, aw-window)
Ingest:        FAILING since 2026-11-20 16:13 (7 cycles), last cycle 2026-11-20 16:19 (15s ago)
  last success  2026-11-20 16:12 (7m 15s ago)
```

The line takes the watchdog's backend verdict, by its threshold
(`backend_minutes`, 5 by default). A last cycle older than that while aw-afk
shows you active adds `NOT REPORTING for <time> (is \`ingest --watch\`
running?)`; while you were away it adds `; cannot tell: silent, but aw-afk
does not show you active` instead. While a watchdog runs beside the database,
silence counts from when it began watching (its saved state), so just after it
resumes the line can read `; cannot tell: silent, but watched only since the
watchdog resumed`. With no watchdog running there (none ran in the last 3
minutes, as in dev), status judges the whole recent past as watched. With no
file the line reads `no \`ingest --watch\` has reported yet`.

`ActivityWatch:` is the watchdog's verdict too: `no` and the banner while it
is unreachable, and `; PROBLEM: not advancing (<sources>)` after the sources
when one of this host's AFK or window sources has not advanced past its
threshold. Status never writes the watchdog's state, notifies or reopens
ActivityWatch.

Read-only: never creates, migrates or writes, and never changes the spool.
The last four sections (illustrative above) come after the rest whatever
state the database is in. The backups, like everything before them, are the
given database's own, read beside it; the three `Stable` sections describe
the stable install whichever profile runs `status` or database it is given.
The backend's last cycle is the `Ingest:` line, read beside the database too,
so a dev `status` shows dev's backend, not stable's:

- **Backups**: the backups beside the database `status` reports on, read from
  the files alone (nothing is opened, and a file removed while they are
  listed is skipped): the latest daily backup's day, when it was written and
  its size, how many days are kept, the pre-update backups when there are
  any, and the folder. Every kept file passed the integrity
  check when it was taken, since a copy that fails is never kept. A
  `warning: no daily backup since <day>` follows when the newest is older
  than yesterday. Before the first, the section is one line:
  `none yet (the daily backup takes one a day into .../backups/daily)`.
- **Stable install**: this run's profile, and the version `current` and
  `previous` point at, with when its build finished; `none` before `install`.
  `agent` is the commit the app at the capture agent's fixed path was built
  from and when it was put there, read from `installed-agent.json` (`built
  from unknown` without that record or the app), so drift from `current`
  shows. Under it sits the update log's last `agent fell back` line, when there
  is one and no later update installed or kept an agent (its outcome
  `updated and verified`, `installed, not verified` or `unchanged`) and no
  later rollback moved it: `fell back <tried> -> <kept>, ...: <reason>`.
  `last update` is the update log's last line that moved `current`, skipping
  agent lines: `updated <from> -> <to>`,
  `rolled back <from> -> <to>`, or `fell back <tried> -> <kept>, ...: <reason>`
  (`none yet` before the first, `unreadable update log: ...` for a damaged one).
- **Stable install's LaunchAgents**: what launchd says about the backend, the
  daily backup, the watchdog, the ActivityWatch login agent and the capture
  agent (the backup, the watchdog and the ActivityWatch opener are usually
  `loaded, not running` between runs) (`loaded, running (pid N)`, `loaded, not running`,
  `installed, not loaded`). Only an agent whose plist is installed is looked
  up; one without is `not installed`. The stopgap backend is looked up by
  label whenever the live folder exists, and listed while its plist is there
  or it is loaded (`, plist deleted` when only launchd still has it), with a
  warning while it is loaded. When launchctl cannot be asked, the section is
  one line, `cannot ask launchd: <reason>`, and the exit code is unchanged.
- **Stable watchdog**: the stable watchdog's last run and its findings from
  `watchdog.json` beside the live database, with when a current problem was
  last notified, any ActivityWatch reopens in the last hour, and errors from
  that run; `none yet` before its first run, and a warning when it last ran
  more than 3 minutes ago (its LaunchAgent is not running it).
Gaps are reported as unobserved time, never assumed idle, and are checked up
to each source's settled-until time. Small lag is normal — an ActivityWatch
source is settled only up to the start of its current, still-growing event. A
source whose progress has no settled time shows `settled until - (progress
moved 30s ago)` instead.

`ax-text` captures are instants, so its gaps follow their own rule. A record
of any kind explains the minute on either side of it (twice the agent's 30s
heartbeat). A pause explains the time until the next record, normally its
`resumed`. A sleep (a `slept` record) explains the time until its `woke`, or,
if that was lost, until the next record or the first `aw-afk` active stretch
after it, whichever comes first. A pause or sleep from before the range counts
too. A stretch of
5m or more is unobserved when `aw-afk` shows you active and nothing explains
it; where `aw-afk` has no data and nothing explains it, the stretch *cannot be
judged*, never idle or active. The range ends at the last stored record while
the spool still holds records (finished files or a non-empty `open.part`),
otherwise now. `aw-afk` includes the newest AFK event from ActivityWatch, when
it is reachable, even before it is stored.

The capture agent section:

- **last capture**: the newest capture, stored or still in the spool
  (excluded, pause and sleep records are not captures).
- **alive**: the watchdog's capture agent verdict, by its threshold
  (`capture_agent_minutes`, 5 by default): `yes` when the newest record,
  stored or still in the spool, is within it; `NO` when `aw-afk` shows you
  active for over a minute since it within the threshold's last stretch;
  `paused` while capture is paused; otherwise `cannot tell`, with why (aw-afk
  does not show you active, or a running watchdog has not watched long
  enough since it resumed).
- **spool**: finished `*.jsonl` files waiting to be ingested and how long the
  oldest has waited, then the files set aside in `unreadable/`. `open.part`
  and `agent.lock` are not counted. The spool path resolves as for `ingest`.
- **today**: the stored captures and excluded records since local midnight,
  how many of those captures were cut off or timed out, and the `slept` and
  `woke` records. Records still in the spool count once ingested.
- **paused**: `yes, since ...` when the newest record, stored or still in the
  spool, is `paused`: any later record ends a pause.
- **app agreement**: each stored capture in the `ax-text` coverage range,
  checked against the app `aw-window` shows in front at its capture time. A
  capture matches when an `aw-window` span within 2s of it (the window
  watcher polls once a second) names the same app, ignoring case; otherwise
  it differs from the nearest such span. A capture with no `aw-window` span
  within 2s is counted apart, never as a match. When no capture can be
  judged, the line reads `cannot be judged: no aw-window data from this
  machine`, or `... near any capture` when there are spans but none within
  2s of a capture. The three most common differing `captured -> aw-window`
  pairs follow. Only app names are shown, never titles or text. Only this
  machine's window buckets count, the ones ActivityWatch names
  `<watcher>_<this hostname>`, so a bucket synced from another machine is
  ignored. `aw-window` includes the newest window event from ActivityWatch,
  when it is reachable, even before it is stored.

Before the agent has stored anything, the section is one line plus the spool:

```
Capture agent: has not reported yet (no ax-text records stored)
  spool         3 finished files waiting (oldest 2m 30s), 0 in unreadable/  (.../ComputerHistory/spool)
```

The screenshots section reads only stored `screenshot` records, never the
screenshots folder, through an index on their status, capture time and image
size, so it stays quick at months of records. Every stored record counts, by
its own capture time, including one dated after now when the agent's clock
runs ahead:

- **last kept**: the newest `kept` record, its app and the image path it
  names (relative to the data folder).
- **today** and **all stored**: records by status, since local midnight (the
  midnight's own offset, so a daylight saving changeover day starts on time)
  and in total. Records still in the spool count once ingested.
- **disk**: the `image_bytes` of the `kept` records, in total and today. An
  image left without a record is not counted.
- **warning**: printed when a `no-permission` record is newer than every
  `kept` and `duplicate` record and the newest `no-permission` record is at
  most 5 minutes old (the window in which the capture agent counts as alive),
  with the time of the first `no-permission` record after the last screenshot
  taken. `secure-field` and `failed` records neither raise nor clear it.
- **permission**: printed instead of the warning once that newest
  `no-permission` record is older, as when screenshots were turned off or the
  agent stopped: when the records last said the grant was missing, and since
  when. It is information, not a warning.

After the end-to-end check's scripted session, whose last two captures lost
the grant, run a day later so the records are old (real output):

```
Screenshots:
  last kept     2026-11-18 01:05 (1d 20h ago), Calculator, screenshots/2026-11-18/44261db4-595d-49ef-ae79-3b034eced225.jpg
  today         0 kept, 0 duplicate, 0 secure-field, 0 no-permission, 0 failed
  all stored    4 kept, 1 duplicate, 1 secure-field, 2 no-permission, 1 failed
  disk          299.3 KB in total, 0 B today (from kept records)
  permission    last recorded missing 2026-11-18 01:09 (1d 20h ago), missing since 2026-11-18 01:07 (1d 20h ago); no screenshot record since says whether it is held
```

`screenshot` coverage is not checked: coverage is judged from `ax-text`
records, so the coverage gaps list says `screenshot: not checked` after the
`ax-text` check, and says nothing about screenshots when that check has
nothing to judge. With no screenshot records stored, the section is one line:

```
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
range covers all its history); existing progress is never moved. A source
whose progress has no settled time is backfilled up to now and its progress
is left alone.

The JSON log gets one `backfill started` record (streams, chunks, range), a
`backfill progress` record at each fifth of the chunks (about 4 for a 51-day
backfill of three sources), `backfill failed` with its traceback if it stops,
and `backfill finished` with the totals and `duration_ms` however it ends.
Each chunk is a DEBUG record. Real output (`computer-history logs --logger
sources.backfill`):

```
2026-11-20 17:18:45 INFO    sources.backfill [backfill b79404d0]  backfill started  chunks=3 start=2026-11-17T08:00:00+00:00 end=2026-11-21T01:18:32.801132+00:00
2026-11-20 17:18:45 INFO    sources.backfill [backfill b79404d0]  backfill progress  chunks_done=1 chunks=3 inserted=0
2026-11-20 17:18:45 INFO    sources.backfill [backfill b79404d0]  backfill progress  chunks_done=2 chunks=3 inserted=0
2026-11-20 17:18:45 INFO    sources.backfill [backfill b79404d0]  backfill finished  outcome=ok chunks_done=3 chunks=3 inserted=0 skipped=23 held_back=0 duration_ms=5
```

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
adapter's projector, the same one ingest used. Needed only after changing a
projector (`activitywatch/normalize.py`, `capture_spool/normalize.py`) or
`text.py`. Aborts (and rolls back) if too many rows fail to project or the
result would shrink suspiciously. It also aborts, without counting them as
malformed, when observations come from a source this version has no adapter
for:

```
rebuild-signals aborted: no source adapter projects 'screenshot', the source of 12 stored observations (first id: 7); rolled back, signals unchanged
  this computer-history has no adapter for that source; rebuild with the version that ingested it
```

The JSON log gets `rebuild started`, a `rebuild progress` record at each fifth
of the observations (only past 10,000 of them), and one `rebuild finished`
however it ends, with `outcome`, `duration_ms`, the signal counts and `failed`
(observations that could not be projected). It is an ERROR when the rebuild
aborted (with the reason in `error`) or failed (with its traceback). Real
output:

```
2026-11-20 17:18:45 INFO    sources.projection [rebuild-signals f7a50a1b]  rebuild started  allow_shrink=False
2026-11-20 17:18:45 INFO    sources.projection [rebuild-signals f7a50a1b]  rebuild finished  outcome=ok duration_ms=1 signals_before=28 signals_after=28 failed=0
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
one already in the dataset cache (`reused from the cache`), and copies every
file of it into `--out`: the database, the manifest of true answers, and any
rendered source files, such as the spool files in `rendered-spool/`. That folder
is not named `spool/`, so `status` on the copied database finds no spool files
waiting: they are already ingested. Every field of the dataset's inputs is
a flag: `--persona`, `--scenario`, `--tier` and `--seed` are required, and
their choices are whatever the synthetic package registers (tiers: day, week,
month, year); `--start` and `--timezone` move the range, and `--heavy` alone (or
`--heavy 3` for another factor) makes the persona a heavier user (switching
twice as often, twice the text, weekends worked). The same inputs always give the same database contents.

It refuses, with exit code 1, to write into a live folder: the live folder
`~/Library/Application Support/ComputerHistory/`, the profile's default
database folder, the folder of
`$COMPUTER_HISTORY_DB` or of a global `--db-path`, and `$COMPUTER_HISTORY_SPOOL`,
and to replace a file or folder that holds one of them.
Paths are compared after resolving symlinks and ignoring letter case, so
`~/library/application support/computerhistory` is refused too. It refuses an
`--out` that already holds any file it would write (`... already holds
history.db, manifest.json; pass --force to replace them`); `--force` replaces
just those, plus stale `-wal`/`-shm` files, and leaves the folder's other files
alone. A dataset that can't be built or copied (a cache on a filesystem
without WAL, say) exits 1 with `dev build-db failed: <error>`.

The cache is `$COMPUTER_HISTORY_DATASET_CACHE`, else
`~/Library/Caches/ComputerHistory/datasets/` on macOS (`$XDG_CACHE_HOME`, or
`~/.cache`, then `computer-history/datasets/` elsewhere), shared by every
worktree. An entry is keyed by the inputs, the package's code and migrations,
and the schema, SQLite and Python versions, so any change to ingest rebuilds
it. A build writes into a temporary folder beside the entry and renames it
into place; when two builds race, the loser discards its copy and uses the
winner's entry, which is never moved aside. Delete the
folder at any time: the next request rebuilds, as it does for an entry missing
its database or manifest.

## dev snapshot — the live database, copied into dev

```bash
computer-history dev snapshot           # into the dev folder's history.db
computer-history dev snapshot --force   # replace the copy already there
computer-history status                 # dev now reads the copy
```

Real output, home shortened to `~`, taken while another connection committed
about 64,000 write transactions in a loop on the live database:

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

The one sanctioned read of live data from dev, so a change can be tried
against real history. It copies only the default live database,
`history.db` in the live folder `~/Library/Application Support/ComputerHistory/`;
there is no flag for another source, and `$COMPUTER_HISTORY_DB` names the copy's
target, never the source. It opens the live database read-only and copies it with
SQLite's online backup, which takes no write lock: the stable backend keeps
ingesting, and the copy holds what was committed when it started. The copy is
written beside the target, passes `PRAGMA integrity_check`, then takes the
target's place; a copy that fails the check is deleted and the command exits 1
with `dev snapshot failed: the copy of <path> failed its integrity check: <problems>`.
If the live database has no `-wal`/`-shm` files when the
snapshot opens it (no backend running), SQLite creates them, empty; nothing
else in the live folder changes.

It copies the database only, never the spool or screenshots, so screenshot
paths in the copy point at files dev doesn't have. The copy lands in dev's
database: `$COMPUTER_HISTORY_DB` or `--db-path` (global or after `snapshot`)
when set, else `history.db` in the dev folder, and it is refused, exit code 1,
inside the live folder, from stable as from dev (`refused: <path> is in the
live data folder ..., and the dev database is never there, whichever profile
runs. ...`). Like `dev build-db`, it refuses a target that already holds the
database or its `-wal`/`-shm`/`-journal` files unless `--force`, and it checks
again just before the copy takes its place, so a database another run creates
meanwhile is never overwritten. `--force` replaces all of them, but only when
no other process has the database open (`dev snapshot refused: another process
has <path> open; stop the commands using it, such as ingest --watch, and try
again`); it moves the old files aside first and puts them back if the copy
can't take their place. No live database exits 1
with `dev snapshot failed: no database at <path>`. The command never migrates:
`status` reports a copy whose schema this checkout doesn't match, and `ingest`
migrates it.

## dev perf — the performance gate

```bash
computer-history dev perf                      # day and month, against the committed baseline
computer-history dev perf --update-baselines   # record a deliberate change of cost
computer-history dev perf --dataset day --dataset year   # a nightly dataset (also: heavy-year)
computer-history dev perf --counters costs.json          # also write what an update would write
```

Real output, on a Mac whose SQLite is not CI's:

```
SQLite 3.54.1, 54 compile options:
  ATOMIC_INTRINSICS=1 COMPILER=clang-21.0.0 DEFAULT_AUTOVACUUM ...
Baseline: .../computer_history/synthetic/perf_baselines/sqlite-3.45.1.json
  SQLite 3.54.1 is not the baseline's 3.45.1: compared statements, full scans and pages but not VM steps, which CI's perf job checks

operation        dataset      statements      VM steps    pages
ingest           day              13,558       466,079    4,210
rebuild-signals  day               5,192       332,768    4,210
status-reads     day                  15       102,448        -
...
expected to fail, status-reads on month: 340,382 VM steps, over the 45,986 the day dataset allows
...

Performance gate passed.
```

Runs each operation (`ingest` into an empty database, `rebuild-signals`, the
store reads `status` makes, and the capture agent's health) on the developer
persona's `messy` datasets from the dataset cache, once untimed and once with
SQLite's work counted: statements run, VM instructions, full table scans in
the query plans of the reads it ran, and the pages of a database it writes.
It compares those with the one committed baseline,
`computer_history/synthetic/perf_baselines/sqlite-3.45.1.json`, counted on
the SQLite CI's `perf` job runs, and exits 1 on any difference: statements,
scans and pages exactly, VM steps past 2%, cheaper ones too, so an improvement
is locked in by rerunning with `--update-baselines` and saying why in the pull
request. A scan fails unless its statement is on the gate's short allowlist
(the row counts and source totals `status` prints, and rebuild's pass over
every observation). The scaling check fails when a windowed read on month
costs more than twice its day cost, or another operation grows half again
faster than the events; the two known failures are tracked in #84. Each
failure names the operation, counter, before and after, and the statements
that changed most:

```
ingest on day: statements 8,861 -> 12,535 (+41.5%), worse than the baseline
  statements that changed most:
    0 -> 3,674 runs, 0 -> 29,392 VM steps: SELECT id FROM observations WHERE id = ?
```

VM steps differ between SQLite versions (by up to 11% between 3.45.1 and
3.54.1), while statements, scans and pages match exactly. So on another SQLite
the gate leaves VM steps out and says so in one line, and `--update-baselines`
rewrites everything but them. If CI's `perf` job then fails on VM steps alone,
take its counters, the file an update on CI would write:

```bash
gh run download <run-id> -n perf-counters -D /tmp/perf
cp /tmp/perf/perf-counters.json computer_history/synthetic/perf_baselines/sqlite-3.45.1.json
```

The scaling check needs `day` beside a larger dataset and says so when it is
missing. A dataset with no entry reports `no baseline yet` until it is recorded
with `--update-baselines`. The nightly run measures day, year and heavy-year
on `ubuntu-24.04` in about two hours; heavy-year peaks near 12 GB of memory,
and at 17 GB it is built afresh each night rather than cached.

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
stable and `~/Library/Logs/computer-history-dev/` for dev, so a checkout's
runs never mix into the stable backend's log; `logs` reads its own profile's
folder. The file
rotates at 10 MB and keeps 5 old files; every running command appends to it,
taking turns through `computer-history.jsonl.lock`, and whichever rotates it
first, the others follow. `logs` reads them all, oldest first, and skips a
line without a JSON object and an ISO time.
Each record carries `ts` (UTC), `level`, `logger`, `msg`, `run` (an id per
invocation), `cmd`, its fields, and `exc` for a traceback. Real output:

```
2026-11-20 17:15:32 INFO    sources.cycle_report [ingest --watch d5f6018a]  cycle ok: aw-afk +0 (1 dup, 1 held); aw-web +0 (0 dup, 0 held); aw-window +0 (3 dup, 1 held); ax-text +0 (0 dup, 0 held); screenshot +0 (0 dup, 0 held)  duration_ms=12
2026-11-20 17:16:32 ERROR   sources.cycle_report [ingest --watch d5f6018a]  cycle failed: ingest failed on aw-afk: database error: no such table: ingest_progress  duration_ms=2 retry_s=60 streak=1
  | Traceback (most recent call last):
  |   File ".../computer_history/sources/runner.py", line 85, in poll
  |     _poll_stream(conn, source, stream, project, outcomes, now=at)
  ...
  | sqlite3.OperationalError: no such table: ingest_progress
```

```json
{"ts": "2026-11-21T01:16:32.795+00:00", "level": "error", "logger": "computer_history.sources.cycle_report", "msg": "cycle failed: ingest failed on aw-afk: database error: no such table: ingest_progress", "run": "d5f6018a", "cmd": "ingest --watch", "duration_ms": 2, "streams": {}, "failures": [{"stream": "aw-afk", "kind": "database busy", "error": "no such table: ingest_progress"}], "retry_s": 60, "streak": 1, "exc": "Traceback (most recent call last):\n ..."}
```

Text output shows only plain fields; nested ones (`streams`, `failures`) are in
the JSON. Control characters in any value are escaped, so a record is one
line. Window titles, URLs and captured text appear only in DEBUG records. A
command that crashes logs `command crashed` as CRITICAL with its traceback and
exits 1, for example `status` on a database missing `ingest_progress`:

```
2026-11-20 17:17:37 CRITICAL cli.app [status c35947c6]  command crashed
  | Traceback (most recent call last):
  ...
  | sqlite3.OperationalError: no such table: ingest_progress
```

With no records yet, `logs` says `no log records yet in <folder>`. A log file
that cannot be opened is reported once at start (`log file unavailable`), and
one that fails later once (`computer-history: cannot write <path>: <error>`);
stderr logging goes on either way.

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

`--log-level` (`debug`, `info`, `warning`, `error`, `critical`) sets the lowest level
logged, to stderr and to the JSON log. Without it the file gets INFO and
stderr WARNING, since each command prints its own report; `ingest --watch`
logs INFO to stderr too, as stderr is its log. At DEBUG, stderr shows
tracebacks; otherwise it shows an exception's last line and the JSON log keeps
the traceback.

Every command but `dev`, `install` and `uninstall` takes `--db-path`, and so does `dev snapshot`; the networked ones (`ingest`, `status`,
`backfill`, `watchdog`) take `--aw-url`. `ingest`, `status` and `watchdog` also take `--spool-path`;
without it the spool is the `spool/` folder beside the database, so a scratch
database never collects the real spool. Without `--db-path` the database is
the profile's (see Profiles above), and dev refuses any of these paths inside
the live folder. `-h` on any command prints its flags.
