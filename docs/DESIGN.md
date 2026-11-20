# Open Computer History: MVP Design Doc

_Status: draft under active review; last updated 2026-11-18. Companion to
[PRD.md](PRD.md). §10 = open decisions; §11 = decision log (context and
rationale live there)._

**[proposed]** = awaiting Brandon's confirmation. Everything else is decided.

---

## 1. Overview

A local macOS system that records computer activity, classifies it into
projects and work types with an LLM, and exposes the result to AI assistants
(MCP) and a local web UI — ending each week in a review with 1–3 concrete
automation suggestions.

**v1 scope:**

- Capture: ActivityWatch **and** a custom Swift capture agent (AX text +
  screenshots, on-device OCR).
- Corrections and project/work-type management in v1, via MCP write tools and
  the UI. (PRD Later's "manual corrections" = corrections-as-rules.)
- One hard-coded OpenRouter model.
- Full rewrite as a Python package; POC deleted once replaced (M6).

**Principles (kept from the POC):**

- Raw observations are immutable.
- One service layer behind REST, CLI, and MCP.
- Bounded, purpose-built AI tools: summaries by default, evidence on request.
- Honest coverage reporting — gaps are surfaced, never guessed.
- Localhost only, no auth.
- Captured text (titles, URLs, AX/OCR) is untrusted data, never instructions.

## 2. System architecture

```
┌─────────────────────────── macOS ───────────────────────────┐
│                                                              │
│  ActivityWatch          Capture Agent (Swift) [proposed]     │
│  (window, AFK, Chrome)  (AX text, screenshots, OCR)          │
│        │                        │                            │
│        ▼                        ▼                            │
│  ┌──────────────── Ingest: source adapters ───────────────┐  │
│  │  poll / backfill → observations + signals (SQLite)     │  │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             ▼                                │
│  ┌──────────── Classifier (scheduled, hourly-ish) ─────────┐ │
│  │  5-min windows → LLM (OpenRouter, text only) → blocks   │ │
│  │  weekly: bottleneck ranking → review + suggestions      │ │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             ▼                                │
│                     SQLite (single file)                     │
│                             │                                │
│        ┌────────────────────┼────────────────────┐           │
│        ▼                    ▼                    ▼           │
│   REST /api           MCP /mcp             React UI at /     │
│   (UI + scripts)      (read + write)       (FastAPI-served)  │
│                             │                                │
└─────────────────────────────┼────────────────────────────────┘
                              ▼
               Claude (direct) · ChatGPT (Secure MCP Tunnel)
```

- One FastAPI process: API + MCP + UI + scheduler. Capture agent is a
  separate login-launched process; ActivityWatch is a separate app.
- URL layout: REST under `/api/*`, MCP at `/mcp`, React UI at `/`.
- **[proposed]** Package layout:

```
computer_history/
  store/        # SQLite, one module per concern: db (connections + migrations),
                # opening (open for a purpose, report the database's state),
                # observations (ingest writes, projecting each new row),
                # signals (the signal row shape and writes, rebuild),
                # progress (per-source ingest progress), status (read
                # queries), contents (a digest of what the database holds),
                # timefmt, paths
  sources/      # contract (the adapter Protocols), runner (poll + watch),
                # backfill (plan + run in chunks), projection (routes each
                # observation to its adapter's projector, for ingest and
                # rebuild-signals), commit (the one write step, a pull, its
                # signals and its progress, and failure classification, shared
                # by poll and backfill), agent_health (the capture agent's
                # health for status, judged against aw-afk and aw-window),
                # then one adapter per source: activitywatch/, ax_text/,
                # screenshots
                # activitywatch/: client, discovery, pull, normalize (its
                # projectors), adapter (ActivityWatch), position (its progress
                # encoding), history (where a stream's history begins, for
                # backfill), afk (stored and newest AFK spans, for status),
                # frontmost (stored and newest aw-window app spans, for status)
                # ax_text/: paths (where the spool is), spool (finished files:
                # list, read, remove, set aside), record (one line checked
                # against format v1), normalize (its projector), adapter
                # (CaptureSpool: one file per pull); for status, backlog (what
                # waits in the spool), stored (the stored records' kinds and
                # apps, the day's counts), coverage (unobserved stretches,
                # liveness) and agreement (each capture's app against aw-window)
  synthetic/    # synthetic datasets built through the real ingest path:
                # timeline, seeds, persona (+ developer), days (a persona's
                # ordinary days), scenarios, generate (inputs -> timeline),
                # renderer (the contract), activitywatch (+ afk, aw_api: the
                # buckets served in process), build, manifest, cache (built
                # datasets per user, keyed by inputs and code), devdb (a cached
                # dataset copied out, never into a live folder)
  text.py       # text/URL normalization shared by every source
  classify/     # windowing, prompts, OpenRouter client, scheduler jobs
  review/       # bottleneck ranking, weekly review, suggestions
  api/          # FastAPI routes under /api
  mcp/          # MCP tools (read + write)
  cli/          # one module per command, dispatched by app.py
                # (serve, classify-now, review-now arrive with later milestones)
ui/             # React app, built into static files FastAPI serves
capture-agent/  # Swift CLI (separate build)
fixtures/       # files both programs read: spool/records.jsonl is the spool contract
scripts/        # venv-python: picks the interpreter the pre-commit hook and e2e.sh run
docs/
```

## 3. Data model (SQLite)

One SQLite file (`~/Library/Application Support/ComputerHistory/history.db`).
Screenshots live on disk; the DB stores paths and extracted text.

Global rules:

- **Time:** all stored timestamps are UTC ISO-8601, uniform precision. Week/day
  *boundaries* are computed in local time at query time; boundary-spanning
  blocks are clipped when summing.
- **Naming:** project names, work-type names and tags are lowercased and
  trimmed on write. Display casing is a later nicety.

### 3.1 Layer 1: `observations` (raw, immutable)

One generic table; a new capture source = a new `source` value + adapter, no
schema change.

```sql
observations (
  id           INTEGER PRIMARY KEY,
  source       TEXT NOT NULL,      -- 'aw-window' | 'aw-afk' | 'aw-web' | 'ax-text' | 'screenshot'
  source_id    TEXT,               -- id in the source system; dedup on re-ingest
  started_at   TEXT NOT NULL,
  ended_at     TEXT NOT NULL,
  payload      TEXT NOT NULL,      -- source JSON, verbatim
  ingested_at  TEXT NOT NULL,
  UNIQUE (source, source_id)
)
```

- Strictly insert-only: no updates, deletes, or upsert carve-outs. Triggers
  reject any `UPDATE` or `DELETE` on the table.
- **Settled-events rule:** an event is ingested only once closed (superseded,
  or older than a stability margin). Handles AW growing the current event in
  place; the minutes of lag are invisible at hourly classification.

### 3.2 Layer 1.5: `signals` (normalized, rebuildable)

Content sources projected into one typed table so consumers read one shape.
Normalization is computation, not just reshaping: domain extraction from URLs,
text hygiene (capping, whitespace collapse). `ax-text` signals keep the first
10,000 characters; the raw observation keeps everything.

```sql
signals (
  observation_id INTEGER PRIMARY KEY REFERENCES observations(id),
  source      TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  ended_at    TEXT NOT NULL,
  app         TEXT,             -- from aw-window
  domain      TEXT,             -- extracted from url (the "time by site" unit)
  url         TEXT,             -- from aw-web
  title       TEXT,
  text        TEXT,             -- AX / OCR text, cleaned and capped
  extras      TEXT              -- leftover source-specific fields, JSON
)
```

- 1:1 with observations; **PK = observation id** (stable across rebuilds).
- Written in the same transaction as the observation, projected from its
  stored payload by the projector of the adapter that claims its source (§4).
  Ingest and rebuild route through the same `sources/projection.py`, so a
  rebuild reproduces ingest's rows exactly.
- Disposable: `rebuild-signals` wipes and re-projects from raw. No per-row
  versions; one meta-table row records the mapping code version.
- `extras` is write-only: display, never filter/aggregate. A query needing a
  field in it = promote to a column (migration + rebuild).
- AFK is **not** in signals — it's state, not content (§4.3).

### 3.3 Layer 2: derived activity

```sql
projects (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,
  status         TEXT NOT NULL,    -- 'proposed' | 'confirmed' | 'archived'
  merged_into_id INTEGER REFERENCES projects(id),  -- merge tombstone
  created_at     TEXT NOT NULL
)

work_types (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT,                -- in classifier prompt: synonyms this type absorbs
  status      TEXT NOT NULL,       -- 'active' | 'archived'
  created_at  TEXT NOT NULL
)

blocks (
  id           INTEGER PRIMARY KEY,
  started_at   TEXT NOT NULL,      -- 5-minute aligned
  ended_at     TEXT NOT NULL,
  project_id   INTEGER REFERENCES projects(id),     -- NULL = Unassigned
  work_type_id INTEGER REFERENCES work_types(id),   -- NULL = no fit / list empty
  confidence   REAL,
  status       TEXT NOT NULL,      -- 'auto' | 'corrected' (corrected = locked)
  summary      TEXT,               -- one-line LLM description
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
)

block_tags (block_id, tag)         -- search/filter only, never totals
```

- Exactly **one project + one work type per block**: each axis partitions
  time, so totals sum to 100%. Ambiguity → split time or use tags, never
  shared labels.
- `corrected` = locked forever; the classifier never touches it (§6).
- Merges are tombstones: re-proposed duplicate names resolve to the survivor
  (following chains). Renames/merges = reference surgery, no LLM call.
- Project-set changes re-label **unconfirmed** blocks from the last 14 days.
- **Evidence is a query, not a table:** block evidence = signals overlapping
  the block's time range (view `block_evidence_v`). Re-add a stored table
  only if the classifier ever selects/weights signals.

#### Projects vs. work types vs. tags

Independent annotations that meet only inside a block; cross-questions
(bottleneck = project × work type) are aggregations, not stored relationships.
AI freedom per axis is inversely proportional to the damage a wrong AI does:

| | **Projects** | **Work types** | **Tags** |
| --- | --- | --- | --- |
| Question answered | Where did time go? (outcome) | What kind of labor? | What else is worth remembering? |
| Created by | AI proposes (born `proposed`) + user adds | Human only; starts empty | AI, freely; no vocabulary table |
| AI's role | Pick existing or propose new | Select one from active list; inventing impossible | Invent liberally; as many useful tags as fit |
| Human's role | Confirm, rename, merge, archive, add | Own the vocabulary (add/rename/re-describe/archive) | Edit per block |
| Edits reach the AI via | Prompt rebuilt each run; 14-day re-label on changes | Prompt rebuilt each run; `description` teaches synonyms | n/a |
| In time math | Yes — one per block | Yes — the bottleneck axis | Never |
| Use cases | Time by project, timeline | Bottleneck ranking, "editing time overall" | Search: "capcut", "shorts", "ep12" |
| Cost of AI mistake | Duplicate; one merge fixes | Would split bottleneck math — hence no freedom | A search misses |

**Work-type cold start (no seed list):**

- Day 0: capture starts; classification runs with `work_type_id = NULL`.
- Day 1–2: user asks their assistant to propose ~8–12 types from real
  activity; on approval the assistant calls `add_work_type`. No dedicated
  endpoint.
- First empty → non-empty transition: one-time **bootstrap re-label** of auto
  blocks (the only exception to deferred relabel-on-type-change).
- The **nudge** in `get_recording_status` and reviews ("no work types yet…")
  is the entire onboarding mechanism; the empty table is the onboarding state.
- NULL-project / NULL-type blocks are excluded from bottleneck ranking.

### 3.4 Layer 3: reviews and suggestions

Generated and stored by the backend so every client sees the same output.

```sql
reviews (
  id           INTEGER PRIMARY KEY,
  week_start   TEXT NOT NULL,      -- Monday, local time
  trigger      TEXT NOT NULL,      -- 'scheduled' | 'on_demand'
  generated_at TEXT NOT NULL,
  body         TEXT NOT NULL       -- JSON: range, totals, bottlenecks + evidence, narrative
)

suggestions (
  id         INTEGER PRIMARY KEY,
  review_id  INTEGER NOT NULL REFERENCES reviews(id),
  title      TEXT NOT NULL,
  evidence   TEXT NOT NULL,        -- JSON: block ids, hours, recurrence (display-only)
  workflow   TEXT NOT NULL,        -- the automation, for a human to judge
  runnable   TEXT NOT NULL         -- paste-ready prompt or Claude Code command
)
```

- **Snapshots, not deltas:** every generation recomputes the whole week from
  current blocks; no cursor. Mid-week on-demand = Monday-to-now.
- **Never overwritten:** rows per week coexist, ordered by `generated_at`;
  `body` is frozen. Trends are answered from blocks, never across bodies.
- **Suggestions are rows** (future status/dismissal needs addressable ids).
  `workflow` = read and judge; `runnable` = execute as-is; separate columns
  because clients render them differently.

### 3.5 Bookkeeping

```sql
ingest_progress (
  source        TEXT PRIMARY KEY,
  position      TEXT NOT NULL,     -- opaque to the store; the source encodes it
  settled_until TEXT,              -- UTC; the source's data is complete up to here
  advanced_at   TEXT NOT NULL      -- when progress last moved
)
classification_runs (id, started_at, finished_at, range, model, status, error)
```

- **Progress is opaque and moves only with a batch.** `position` is whatever
  the source needs to resume (ActivityWatch: a UTC timestamp; the AX-text
  spool: the time of the latest stored capture, also its `settled_until`,
  since finished files are read oldest first and removed once stored). Only
  `insert_observations` writes it, in the same transaction as the batch,
  either advancing it (incremental ingest) or setting it only if the source
  has none (backfill's last chunk). Status's freshness and gap window and
  backfill planning read `settled_until`; nothing outside the source's
  adapter decodes `position`.

- Two separate frontiers on purpose: ingestion and classified time move
  independently; a blocks-derived watermark would re-classify fully-AFK
  ranges forever.
- `classification_runs` doubles as the LLM audit log.

## 4. Ingestion

Adapter contract: _the adapter pulls raw observations from the stored
position and supplies a projector per stream; the runner writes
`observations` + their `signals` + the new progress in one transaction._
Idempotent via `(source, source_id)`.
Only adapters know payload dialects; everything downstream reads `signals`.

- An adapter (`sources/contract.py`) is a `Source`: `streams()` names the
  streams it feeds (ActivityWatch: `aw-window`, `aw-afk`, `aw-web`; the
  AX-text spool: `ax-text`), and `pull_after(stream, position, now=)` returns
  a `Pull`: settled observations, a held-back count, the new `position`
  (`None` leaves progress as it is) and `settled_until`, plus three fields a
  file-based source needs: `rejected` (records it could not use and skipped),
  `more` (pull again in this poll) and `after_commit` (a step `commit_pull`
  runs once the batch is committed; the spool removes the file there). A
  *stream* is what the store calls a source. Failures raise
  `SourceUnavailable` (`AWError` and the spool's `SpoolError` are ones).
- Every adapter names `projectors`: for each stream it can ever feed (not only
  the ones it feeds now), a function from a stored payload to its `Signal`, or
  `None` for no signal (AFK). An adapter keeps it on the class, so
  `rebuild-signals` can use it without connecting to the source.
  `projector_for(sources)` (`sources/projection.py`) routes an observation to
  the projector of the adapter claiming its stream; two adapters claiming one
  stream differently are refused. The store calls that projector on each
  newly inserted row (re-read duplicates are never projected) and on every
  row at rebuild, in observation-id order: one seam, the same input.
- `reproject_signals(conn)` rebuilds through the known adapters
  (`KNOWN_SOURCES`). An observation whose source no adapter claims raises the
  store's `UnclaimedSource`, and the commit step refuses a pull holding an
  observation from another stream (`StrayObservation`). At ingest either one
  rolls back that stream's batch and is reported as an `ADAPTER` failure;
  other streams and sources go on, and `--watch` keeps polling. A rebuild
  checks every stored source against the claims before projecting anything
  and aborts with signals unchanged; it is never counted as a malformed
  payload.
- A `HistorySource` also supports backfill: `parts`, `history_start`,
  `history_before` (planning facts) and `pull_range(stream, start, end, now=)`.
  Sources with nothing to backfill (the spool) implement only `Source`.
- The runner is source-agnostic. `poll(conn, sources)` (`sources/runner.py`)
  reads every stream of every source, one commit per pull, pulling again
  while a pull says there is `more`; an unavailable source skips the rest of
  its streams and others continue; a busy database ends the cycle; other
  database errors propagate; two sources feeding one stream are refused.
  `watch` repeats it every 60s (injected clock for `now`,
  monotonic timer and sleep for pacing). `run_backfill(conn, source, plans)`
  (`sources/backfill.py`, beside the planning)
  commits chunks oldest first, reports incomplete chunks, and sets a stream's
  first progress in its last chunk's commit (from the first incomplete
  chunk's pull, else the last one), only if the plan covers all its history;
  any failure or Ctrl-C stops it and is reported with what committed.
- The CLI constructs the clients, adapters and connection and passes them in.

### 4.1 ActivityWatch adapter

- Polls `http://127.0.0.1:5600/api/0` every 60s **[proposed]**; window, AFK,
  Chrome buckets. Read-only toward AW.
- Settled-events rule (§3.1) handles AW growing the current event.
- **Zero-history installs are the baseline.** `backfill` (ingesting existing
  AW history) is a one-time command for Brandon's install, not a product
  feature.

### 4.2 Capture agent (Swift)

Separate Swift CLI, login-launched: TCC permissions attach to a stable signed
binary; AX / ScreenCaptureKit / Vision are native. Deliberately dumb —
observe, write spool files, repeat; all intelligence stays in Python.
Screenshot mechanics are still **[proposed]**; the AX mechanics are decided.

- Identity: a windowless `.app` at a fixed path, signed with a self-signed
  certificate so the Accessibility grant survives rebuilds; started by its
  own LaunchAgent from M2.
- A capture is an instant (`started_at = ended_at`).
- Triggers: app switch, window switch, window-title change + 30s heartbeat
  while active; one-second settle delay, at most one capture per second.
- Silent when idle, locked or asleep. Idle is macOS's own
  seconds-since-last-input (threshold configurable, default 180s); the agent
  never reads ActivityWatch. `aw-afk` stays the only source of attended time.
- AX text: focused-window tree walk, content roles only, 50 KB cap with the
  full length and a cut-off flag recorded, 0.25s per-call and 2s per-window
  timeouts. Full text and its hash are written on every capture, changed or
  not. Secure fields (`kAXSecureTextField`) always skipped.
- Denylist: listed apps produce an "excluded" record with no text.
  `pause` / `resume` each write a record. Both make the gap explained, not
  unobserved.
- Screenshots: ScreenCaptureKit → ~1440px JPEG q60 → perceptual-hash dedup →
  disk. Vision OCR **in the agent**; only text crosses to Python; screenshots
  never leave the Mac. Est. ~75–150 MB/day post-dedup.
- Spool handoff: the agent appends JSONL (one record per line, UUID =
  `source_id`) to one open file and renames it to a finished name every
  minute. The backend reads only finished files, stores them, then deletes
  them; no offset cursor, since re-reading is idempotent. Unusable lines are
  skipped and counted; a file with any unusable line, or that cannot be read,
  is moved into `spool/unreadable/`, never deleted. The filesystem is the
  queue; backend downtime just accumulates files.
- Risks: sparse AX trees in Electron/Chrome (screenshots are the complement;
  whether to set the apps' accessibility flag is measured in M2); periodic
  macOS Screen Recording re-confirmation (surface as coverage warning); TCC
  needs a stable binary path + signature. Front-loaded at M2–M3 deliberately.

### 4.3 AFK: raw-only, three consumers

AFK gates and splits activity; it never describes it. Exactly three readers
of raw `aw-afk` rows:

1. Classifier windowing — fully-AFK windows skipped (no digest, no LLM).
2. Block assembly — AFK gaps > 5 min split blocks.
3. Breakdowns — attended = signal intervals ∩ not-afk; responses report both
   `foreground_seconds` and `attended_seconds`.

Semantics: missing AFK data = coverage gap, never attendance; AFK undercounts
passive consumption (video-watching reads idle) — accepted for v1.

## 5. Classification: observations → blocks

Scheduled in the backend (freshness ~1 hour). AI clients never classify on
the fly; they read stored results.

1. **Windowing:** fixed 5-minute windows; digest per window from `signals`
   (apps + titles with durations, domains/URLs, cleaned text). Fully-AFK
   windows skipped.
2. **LLM labelling:** batch N windows per OpenRouter call (one model, text
   only). Prompt: project list (names + descriptions), active work-type list
   (names + descriptions), and the rule that a project is an outcome, never
   an activity kind. Returns per window: project (existing or new), work type
   (selected, never invented), tags (as many as fit), confidence, summary.
3. **Project proposal:** new names create `proposed` rows and label windows
   immediately; proposals resolve against archived names first (merge
   forwarding).
4. **Block assembly:** merge consecutive same-(project, work type) windows;
   split at AFK gaps > 5 min.
5. **Write-back:** insert `status='auto'`; never touch `corrected` (§6). Low
   confidence → `project_id = NULL` (threshold default 0.5 **[value
   proposed]**); `work_type_id = NULL` when nothing fits or list is empty.
6. **Catch-up with a horizon:** classify the gap since the last successful
   run, capped at 14 days back (configurable). Older data is only classified
   via explicit `classify-backfill` — no surprise LLM burn.

Prompt injection is deferred by decision: v1 only validates output (strict
JSON schema; labels checked against known lists).

## 6. Projects and corrections

| Action | Effect |
| --- | --- |
| Confirm project | `status → confirmed`. |
| Rename project | Update `name`; references untouched; no LLM call. |
| Merge A into B | Tombstone + re-point blocks; no LLM call. |
| Add project | New `confirmed` row; appears in next classifier prompt. |
| Add / rename / re-describe / archive work type | Rename = reference surgery; description edits steer the next run; archive hides from prompt. Future classification only, except the bootstrap re-label (§3.3). |
| Correct a block | Set project / work type / tags; `status → 'corrected'`, locked forever. |
| Split a block | `split_block(block_id, at_time)`, snapped to 5-min grid; evidence follows automatically (it's a range query). |
| Project set changes | Re-label unconfirmed blocks, last 14 days. |

- **Time edits in v1 = splitting only.** Splits can't create neighbor
  conflicts; boundary drags/merges wait for evidence they're needed.
- Users edit interpretation only; nothing writes to `observations`/`signals`.
- **Corrected lock enforced in the write statement** (`WHERE status !=
  'corrected'`, one transaction) — never check-then-write, or a correction
  landing mid-classifier-run gets overwritten. Human writes always win.

## 7. Weekly review and bottlenecks

- Week = Monday–Sunday local. Auto-generated at week end; on demand anytime
  (LLM-backed, exempt from 2s target). Generation runs classification
  catch-up first.
- While `work_types` is empty, reviews carry the onboarding nudge.
- **Stage 1 — deterministic (how big):** score each (project × work type)
  pair, **[proposed]** `hours × distinct days`, work blocks only (NULLs
  excluded). Same data in, same ranking out; numbers auditable against
  blocks.
- **Shortlist by materiality, not rank:** every pair clearing a floor
  (**[proposed]** ≥2h in the week, or ≥30 min on 3+ days), capped at ~15.
- **Stage 2 — AI (which are automatable):** LLM gets the shortlist with
  evidence; selects/orders the 1–3 worth suggesting; writes narrative +
  evidence/workflow/runnable. Constraints: no candidates outside the
  shortlist; every pick cites its evidence.
- Stage-1 ranking stored in `reviews.body`; picks become `suggestions` rows.

## 8. Interfaces

### 8.1 MCP tools (`/mcp`)

Read (bounded; summaries by default, evidence on request):

| Tool | Purpose |
| --- | --- |
| `get_recording_status` | Source freshness, coverage gaps, disk usage; onboarding nudge |
| `get_time_breakdown` | Time by project / work type / app / domain / URL; foreground + attended |
| `get_timeline` | A day's blocks in order |
| `list_projects` | Projects with status and totals (`status='proposed'` = approval queue) |
| `get_blocks` | Blocks by range/project, evidence on request |
| `get_weekly_review` | Latest or specified week's review + suggestions |
| `generate_review_now` | On-demand review (slow; runs the LLM) |

Write: `correct_block`, `split_block`, `confirm_project`, `rename_project`,
`merge_projects`, `create_project`, `add_work_type`, `rename_work_type`,
`archive_work_type`. Hard validation; returns the updated object. Tested in
Claude (direct) and ChatGPT (Secure MCP Tunnel).

### 8.2 REST (`/api/*`)

Same service layer, ~one route per MCP tool, plus UI needs (screenshot file
serving — localhost only). Swagger UI at `/docs` is the free admin tool until
the React UI exists.

### 8.3 Web UI (`/`)

React, static files served by FastAPI. V1 = Brandon's testing/viewing tool:
timeline, breakdowns, project management, block correction, review +
suggestions, status, disk usage, screenshot display.

### 8.4 Non-functional

- 2s target for SQLite reads (MCP + UI); LLM-backed actions exempt.
- LaunchAgents start backend + capture agent at login; immediate ingest +
  classification catch-up.
- Localhost only, no auth. Disk usage visible via status tool + UI.

## 9. Milestones

Moved to [milestones.md](milestones.md).

## 10. Open items needing a decision

1. **Capture agent** (§4.2) — five sub-decisions: screenshot scope (frontmost
   window / active display / all displays), heartbeat cadence (30s vs 60s),
   image budget (~1440px JPEG q60), secure-input skip, same-tick AX +
   screenshot capture.
2. **Bottleneck numbers** (§7): formula `hours × distinct days`; materiality
   floor ≥2h or ≥30min on 3+ days. (Mechanism decided; values not.)
3. **Low-confidence threshold** (§5): default 0.5, configurable.
4. **AW polling interval** (§4.1): 60s.
5. **Partial-week breakdowns:** `get_time_breakdown` over any range suffices —
   confirm no separate tool needed.
6. **Review `body` JSON shape** (§3.4): range / totals / bottlenecks /
   narrative.
7. **`get_weekly_review` default:** serves the week's latest review.
8. **Empty weeks** (§7): still store a review ("no classified work") so a
   missing review always means a bug.
9. **Keep `reviews.trigger`** (the one defensible cut from the final audit;
   recommendation: keep).

Structural-but-unblessed (silence = consent): package layout (§2).

## 11. Decision log

Context and rationale for decisions live here, not in the sections above.

- **2026-11-16 — initial draft.** Scope: capture agent and corrections in v1,
  one model, full rewrite. Architecture, milestones.
- **2026-11-17 — data model.** Two-layer `observations` + `signals`: one
  generic raw table keeps "new source = no schema change"; the typed signals
  layer centralizes payload knowledge in adapters and exists because
  normalization is computation (domain extraction, text hygiene), which SQL
  views can't do well. Signals PK = observation id so rebuilds can never
  dangle references. Wipe-and-rebuild beats per-row mapping versions at this
  scale. `extras` write-only so per-source JSON never leaks back into
  consumers. AFK stays raw: it's a state that gates content, never content —
  putting it in signals would tax every content query with a filter.
  Corrections = relabel + split only: splits can't create neighbor conflicts;
  drags/merges repartition the day and wait for evidence of need.
- **2026-11-17 — Layer 2.** Work types are a curated closed vocabulary (AI
  selects, never invents) because their value is comparability — LLM-coined
  near-duplicates ("coding"/"programming") would silently split bottleneck
  math. Projects are the opposite: an open set the AI proposes, because
  discovering them is the product. Tags are structurally excluded from time
  math, so AI freedom there is costless. `description` on work types is how
  the user teaches synonym absorption. AI-proposed types, consolidation
  suggestions and relabel-on-type-change → PRD Later.
- **2026-11-17 — onboarding.** Zero-history install is the baseline
  (Brandon's AW backfill is a one-time convenience). No seed work types: a
  seed is someone else's taxonomy. AI proposes from real data after a day or
  two of capture, conversationally via MCP read tools + `add_work_type`;
  human approves; bootstrap re-label heals the typeless backlog. A day-0
  interview was rejected: self-reported taxonomies are the problem the
  product corrects. The empty table is the onboarding state (nudge), so no
  wizard or state machine exists.
- **2026-11-17 — final schema audit.** `block_evidence` table dropped: the
  classifier reads all signals in a window, so evidence is pure time overlap
  — a stored table was a cache adding rebuild/split machinery for zero
  information (re-add only if the classifier ever selects/weights signals).
  `projects.created_by` dropped: status already encodes provenance (AI-born =
  `proposed`); after approval origin changes no behavior. `confidence` kept
  for a future "review these first" UI. Settled-events rule resolves the
  contradiction between insert-only observations and AW's growing events.
  Classification horizon prevents a large first ingest from triggering an LLM
  burn. UTC-everywhere except local week/day boundaries (a UTC week boundary
  lands mid-Sunday locally). Lowercase naming kills case-variant duplicates.
  Corrected-lock lives in the write statement because the classifier is
  read-think-write and a check-then-write races a mid-run correction.
- **2026-11-18 — review engine.** Two-stage ranking: deterministic scoring
  answers "how big" (LLM-ranked magnitudes would hallucinate and drift);
  AI answers "how automatable" (hours × days can't tell meetings from
  automatable editing). Shortlist by materiality floor, not top-N: a fixed
  rank clips material pairs in dense weeks and passes junk in sparse ones;
  with a floor, nothing meaningful can be excluded. Reviews are full-week
  snapshots (deltas would make "the review of week X" depend on trigger
  history); never overwritten so corrections can't rewrite history. Block
  assembly confirmed; tags uncapped; low-confidence → NULL project.
- **2026-11-18 — milestones.** Ingestion-first ordering: classifier built
  once against the full signal set (no prompt rework when text arrives),
  data accumulates as an eval corpus, TCC risk front-loaded while a pivot is
  cheap. Accepted cost: later aha moment; mechanical value (breakdowns,
  attended time) ships early. Swagger `/docs` is the admin tool until React.
  "What needs approval?" = `list_projects(status='proposed')` + work-type
  nudge; no new tool. URL layout (`/api` + `/` + `/mcp`) accepted.
- **2026-11-18 — M2 capture agent.** Self-signed certificate: an ad-hoc
  signature changes with every build, so TCC would drop the grant each time.
  The agent's LaunchAgent moved from M4 to M2 because a terminal-launched
  binary borrows the terminal's grant and proves nothing about its own.
  Native idle detection instead of reading AW: same macOS idle timer, a few
  lines, and no dependency on AW being up. Hash-skip dropped: the storage
  saved is small next to screenshots, and markers force every reader to look
  back for text that may be lost; full text plus a hash keeps every record
  self-contained and lets later stages collapse duplicates. Cap raised to
  50 KB (keep raw, trim later) with cut-offs recorded; signals keep 10,000
  characters because they are rebuildable. Finished-file handoff replaced the
  (file, offset) cursor: the backend never reads a file being written, so no
  byte position or partial-line handling is needed, and unique `source_id`
  makes re-reading harmless. Storage compaction (store-once, compression,
  retention) deferred until real sizes exist.
