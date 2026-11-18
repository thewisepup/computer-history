# Open Computer History: MVP Design Doc

_Status: draft under active review; last updated 2026-11-18. Companion to
[PRD.md](PRD.md). §10 lists what still needs a decision; §11 is the decision
log._

**[proposed]** = recommendation awaiting Brandon's confirmation. Everything
else is decided.

---

## 1. Overview

A local macOS system that records computer activity, classifies it into
projects and work types with an LLM, and exposes the result to AI assistants
(MCP) and a local web UI — ending each week in a review with 1–3 concrete
automation suggestions.

**v1 scope:** ActivityWatch **and** a custom capture agent (AX text +
screenshots, on-device OCR); block corrections and project management via MCP
write tools and the UI ("manual corrections" on the PRD Later list means
corrections-as-rules); one hard-coded OpenRouter model; full rewrite as a
Python package — the POC is deleted once the new pipeline passes its tests.

**Kept POC principles:** raw observations immutable; one service layer for
REST/CLI/MCP; bounded purpose-built AI tools; honest coverage reporting;
loopback only; captured text is untrusted data.

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

One FastAPI process hosts API + MCP + UI and runs the scheduler. The capture
agent is a separate login-launched process; ActivityWatch is a separate app.

**URL layout:** REST under `/api/`*, MCP at `/mcp`, React UI at `/`
(avoids route collisions with the POC's root-level routes).

**[proposed] Package layout:**

```
computer_history/
  store/        # SQLite schema, migrations, queries
  sources/      # one adapter per source: activitywatch, ax_text, screenshots
  classify/     # windowing, prompts, OpenRouter client, scheduler jobs
  review/       # bottleneck ranking, weekly review, suggestions
  api/          # FastAPI routes under /api
  mcp/          # MCP tools (read + write)
  cli.py        # serve, status, backfill, rebuild-signals, classify-now, review-now
ui/             # React app, built into static files FastAPI serves
capture-agent/  # Swift CLI (separate build)
docs/
```

## 3. Data model (SQLite)

One SQLite file (`~/Library/Application Support/ComputerHistory/history.db`).
Screenshots live on disk; the DB stores paths and extracted text.

**Time rule:** all stored timestamps are UTC ISO-8601 at uniform precision
(TEXT comparison works lexicographically). Sole exception: week/day
*boundaries* are computed in the user's local timezone at query time, and
boundary-spanning blocks are clipped into each side when summing.

**Naming rule:** project names, work-type names and tags are lowercased and
trimmed on write — case variants can never create duplicates. Display casing
is a later nicety.

### 3.1 Layer 1: raw observations (immutable)

One generic table meets the extensibility requirement: a new capture source is
a new `source` value plus an adapter, not a new table.

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

Strictly insert-only: no updates, no deletes, no upsert carve-outs. Sources
that grow events in place (AW extends the current window event) are handled by
the **settled-events rule**: an event is ingested only once closed —
superseded by a newer event or older than a short stability margin. The few
minutes of lag are invisible at hourly classification, and immutability holds
with no exceptions.

### 3.2 Layer 1.5: signals (normalized, rebuildable)

Content sources projected into one typed table, so consumers read one shape
instead of per-source payload JSON. Normalization is computation, not just
reshaping: domain extraction from URLs, text hygiene (capping, whitespace
collapse, dedup against the previous capture).

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

- **1:1 with observations; PK = observation id** — signals carry no original
information, and stable ids make rebuilds invisible to anything referencing
a signal.
- **Written in the same transaction** as their observation — drift can only
come from mapping bugs, never crashes.
- **Disposable:** `rebuild-signals` wipes and re-projects the table whenever
mapping code improves (full rebuild is minutes at this scale; a meta-table
row records which code version built it — no per-row versions).
- `**extras` is write-only:** display it, never filter/aggregate on it. A
query needing a field in `extras` means promoting it to a column
(migration + rebuild).
- **AFK is not in signals** — it's a state, not content (§4.3). A second
state-like source later would justify a `state_spans` table; one doesn't.

### 3.3 Layer 2: derived activity

```sql
projects (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,
  status         TEXT NOT NULL,    -- 'proposed' | 'confirmed' | 'archived'
  merged_into_id INTEGER REFERENCES projects(id),  -- merge tombstone; blocks re-pointed
  created_at     TEXT NOT NULL
)
-- No created_by: status already carries the provenance that matters (AI-created
-- are born 'proposed', user-created 'confirmed'); after approval, origin
-- changes no behavior.

work_types (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT,                -- fed into the classifier prompt: the synonyms
                                   -- this type absorbs ("coding, debugging, devops")
  status      TEXT NOT NULL,       -- 'active' | 'archived'
  created_at  TEXT NOT NULL
)

blocks (
  id           INTEGER PRIMARY KEY,
  started_at   TEXT NOT NULL,      -- aligned to 5-minute boundaries
  ended_at     TEXT NOT NULL,
  project_id   INTEGER REFERENCES projects(id),     -- NULL = Unassigned
  work_type_id INTEGER REFERENCES work_types(id),   -- NULL = no type fits / list empty
  confidence   REAL,
  status       TEXT NOT NULL,      -- 'auto' | 'corrected'  (corrected = locked)
  summary      TEXT,               -- one-line LLM description
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
)

block_tags (block_id, tag)         -- search/filter only, never totals
```

Key decisions:

- **Exactly one project and one work type per block** — each axis partitions
time, so totals sum to 100% and the bottleneck math can't double-count.
Ambiguity is handled by splitting time or by tags, never by sharing labels.
- `**corrected` = locked forever.** The classifier never touches it (§6).
- **Merges are tombstones:** `merged_into_id` keeps the old row as a
forwarding address, so a re-proposed duplicate name resolves to the survivor
(following chains) instead of resurrecting. Renames/merges are reference
surgery — no LLM call. Project-set changes re-label **unconfirmed** blocks
from the last 14 days.
- **Evidence is a query, not a table:** a block's evidence = signals whose
time range overlaps the block's (kept as view `block_evidence_v`). The
classifier reads *all* signals in a window, so a stored table would cache a
range query while adding rebuild/split coordination for zero information.
**Re-add trigger:** if the classifier ever selects or weights signals
(corrections-as-rules), "what the model saw" must be stored again.

#### Projects vs. work types vs. tags

Three independent annotations; they never reference each other and meet only
inside a block. Every cross-question (bottleneck = project × work type) is an
aggregation over blocks, not a stored relationship. AI freedom per axis is
inversely proportional to what breaks when the AI is wrong:

| | **Projects** | **Work types** | **Tags** |
| --- | --- | --- | --- |
| Question answered | *Where did this time go?* (outcome served) | *What kind of labor was it?* | *What else is worth remembering?* |
| Created by | Both: AI proposes from activity (born `proposed`, labels blocks immediately); user adds | Human only: starts empty; user adds directly or via assistant (`add_work_type`) | AI, freely: no vocabulary table exists |
| AI's role | Pick existing or propose new | Select exactly one from the active list; inventing impossible (strict validation → Unassigned) | Invent liberally — as many useful tags as fit (lowercased, deduped) |
| Human's role | Confirm, rename, merge, archive, add | Own the vocabulary: add, rename, re-describe, archive | Edit per block via `correct_block` |
| How edits reach the AI | Prompt rebuilt from DB each run; project changes re-label unconfirmed blocks (14 days) | Prompt rebuilt each run; `description` teaches synonym absorption | n/a |
| In time math | Yes — one per block | Yes — one per block; the bottleneck axis | Never |
| Cost of an AI mistake | Duplicate project — one merge fixes it | Would silently split bottleneck math — hence no freedom | A search misses |

**Work-type cold start (no seed list).** `work_types` starts empty; the design
assumes a zero-history fresh install (§4.1). Day 0: capture starts;
classification runs with `work_type_id = NULL` — nothing stalls. Day 1–2: the
user asks their assistant to propose ~8–12 types from real activity
(conversational: MCP read tools → draft with descriptions → `add_work_type` on
approval; no dedicated endpoint). First empty → non-empty transition triggers a
one-time **bootstrap re-label** of auto blocks — the single exception to
deferred relabel-on-type-change. The **nudge** ("no work types yet — ask your
assistant to propose a list") in `get_recording_status` and reviews is the
entire onboarding mechanism: the empty table *is* the onboarding state. A
day-0 interview is deliberately out — self-reported taxonomies are the problem
the product corrects. NULL-project/NULL-type blocks are excluded from
bottleneck ranking; real personal-vs-work distinction is PRD Later.

### 3.4 Layer 3: reviews and suggestions

Generated and stored by the backend so every client sees the same output,
served in milliseconds.

```sql
reviews (
  id           INTEGER PRIMARY KEY,
  week_start   TEXT NOT NULL,      -- Monday, local time
  trigger      TEXT NOT NULL,      -- 'scheduled' | 'on_demand'
  generated_at TEXT NOT NULL,
  body         TEXT NOT NULL       -- JSON: range, totals, bottlenecks w/ evidence, narrative
)

suggestions (
  id         INTEGER PRIMARY KEY,
  review_id  INTEGER NOT NULL REFERENCES reviews(id),
  title      TEXT NOT NULL,
  evidence   TEXT NOT NULL,        -- JSON: block ids, hours, recurrence (display-only)
  workflow   TEXT NOT NULL,        -- the automation, for a human to read and judge
  runnable   TEXT NOT NULL         -- paste-ready prompt or Claude Code command
)
```

Semantics:

- **Snapshots, not deltas.** Every generation recomputes the whole week from
current blocks — no cursor, no "since last review." Mid-week on-demand runs
cover Monday-to-now; the scheduled run covers the full week regardless of
earlier triggers. Full recompute is idempotent and absorbs corrections
automatically.
- **Never overwritten.** Multiple rows per `week_start` coexist, ordered by
`generated_at`; `body` is frozen so later corrections can't rewrite what a
review said. Trends are answered from blocks, never across review bodies.
- **Suggestions are rows because they have an afterlife:** deferred
status/dismissal needs addressable ids. `workflow` (read and judge) and
`runnable` (execute as-is) stay separate columns because clients render
them differently — prose vs. copy-and-run.

### 3.5 Bookkeeping

```sql
ingest_cursors (source, last_seen)      -- per-source ingestion frontier
classification_runs (id, started_at, finished_at, range, model, status, error)
```

Two separate frontiers on purpose (ingestion vs. classified time move
independently); a blocks-derived watermark would re-classify fully-AFK ranges
forever. `classification_runs` doubles as the LLM audit log.

## 4. Ingestion

Adapter contract: _pull new data since a cursor, write `observations` +
`signals` in one transaction, advance the cursor._ Idempotent via the
`(source, source_id)` unique key. Only adapters know payload dialects;
everything downstream reads `signals`.

### 4.1 ActivityWatch adapter

- Polls `http://127.0.0.1:5600/api/0` every 60s **[proposed]** for window,
AFK, and Chrome web buckets.
- **Zero-history installs are the baseline.** Nothing downstream may depend on
pre-existing data. Ingesting existing AW history is a one-time `backfill`
command for Brandon's own install, not a product feature.
- AW grows the current event in place → settled-events rule (§3.1).
- Read-only toward ActivityWatch.

### 4.2 Capture agent (Swift) **[proposed: mechanics under discussion]**

Separate Swift CLI, login-launched: TCC permissions (Accessibility, Screen
Recording) attach to a stable signed binary, and AX / ScreenCaptureKit /
Vision are native APIs. The agent is deliberately dumb — observe, write spool
files, repeat; all intelligence stays in Python.

- **Triggers:** app/window switch + 30s heartbeat while active; silent when
locked or AFK (reads AW's AFK state rather than reimplementing it).
- **AX text:** focused-window tree walk, content roles only, ~10 KB cap,
hash-skip unchanged text, per-call timeouts (hung apps cost one capture,
not the agent). Secure fields (`kAXSecureTextField`) always skipped —
engineering hygiene, not a privacy feature.
- **Screenshots:** ScreenCaptureKit → downscale (~1440px JPEG q60) →
perceptual-hash dedup → disk; Vision OCR **in the agent**, so only text
ever reaches the Python/cloud side. Screenshots never leave the Mac.
Est. ~75–150 MB/day post-dedup.
- **Spool handoff:** hourly-rotated JSONL, one capture per line (UUID =
`source_id`); backend adapters tail with a (file, offset) cursor. No IPC —
the filesystem is the queue; backend downtime just accumulates files.
- **Known risks:** Electron/Chrome expose sparse AX trees (screenshots+OCR
are the complement); macOS re-confirms Screen Recording periodically
(surface as a coverage warning, not silent failure); TCC under LaunchAgents
needs a stable binary path and signature. This risk is deliberately
front-loaded (M2–M3): it's exercised while a pivot is still cheap, and
capture runs for weeks before classification needs its output.

### 4.3 AFK: raw-only, three consumers

AFK gates and splits activity; it never describes it. Exactly three readers of
raw `aw-afk` rows:

1. **Classifier windowing** — fully-AFK windows skipped (no digest, no LLM).
2. **Block assembly** — AFK gaps > 5 min split blocks.
3. **Breakdowns** — attended = signal intervals ∩ not-afk intervals;

   responses report both `foreground_seconds` and `attended_seconds`.

Pinned semantics: **missing AFK data is a coverage gap, never attendance**
(report foreground time + warning); AFK undercounts passive consumption
(video-watching reads as idle) — accepted for v1.

## 5. Classification: observations → blocks

Scheduled in the backend (freshness ~1 hour). AI clients never classify on the
fly; they read stored results.

1. **Windowing.** Fixed 5-minute windows; digest per window from `signals`

   (apps + titles with durations, domains/URLs, cleaned text). Fully-AFK
    windows skipped.
2. **LLM labelling.** Batch N windows per OpenRouter call (one hard-coded

   model, text only). Prompt contains: project list (names + descriptions),
    active work-type list (names + descriptions — descriptions teach synonym
    absorption), and the rule that a project is an outcome, never an activity
    kind ("video editing" is a work type, not a project). Returns per window:
    project (existing or newly proposed), work type (selected, never
    invented), as many useful tags as fit, confidence, one-line summary.
3. **Project proposal.** New names create `proposed` rows and label windows

   immediately; proposals resolve against archived names first (merge
    forwarding).
4. **Block assembly.** Merge consecutive same-(project, work type) windows;

   split at AFK gaps > 5 min.
5. **Write-back.** Insert `status='auto'`; never touch `corrected` (§6).

   Low confidence → `project_id = NULL` rather than a guess (threshold
    default 0.5 **[value proposed]**); `work_type_id = NULL` when nothing fits
    or the list is empty.
6. **Catch-up with a horizon.** On startup/after sleep, classify the gap

   since the last successful run — capped at 14 days back (configurable).
    Older data is ingested and mechanically queryable, but classified only via
    explicit `classify-backfill` — a large first ingest can never trigger a
    surprise LLM burn.

**Prompt injection (deferred by decision):** captured text flows into the
prompt; v1 only validates output (strict JSON schema, labels checked against
known lists).

## 6. Projects and corrections

| Action | Effect |
| --- | --- |
| Confirm project | `status → confirmed`. |
| Rename project | Update `name`; references untouched; no LLM call. |
| Merge A into B | Tombstone + re-point blocks; no LLM call. |
| Add project | New `confirmed` row; appears in next classifier prompt. |
| Add / rename / re-describe / archive work type | Rename = reference surgery; description edits steer the next run; archive hides from prompt, old blocks untouched. Affects future classification only (relabel-on-type-change is PRD Later), except the one-time bootstrap re-label (§3.3). |
| Correct a block | Set project / work type / tags; `status → 'corrected'`, locked forever. |
| Split a block | `split_block(block_id, at_time)`, snapped to the 5-min grid; evidence is a time-range query so each half's follows automatically. |
| Project set changes | Re-label unconfirmed blocks from the last 14 days. |

**Time edits in v1 = splitting only.** A split subdivides what a block already
owns — no neighbor conflicts, no gap-filling policy. Boundary drags and merges
repartition the day and wait for evidence they're needed. Users edit
interpretation only: nothing ever writes to `observations` or `signals`.

**The corrected lock is enforced in the write statement, not at read time.**
The classifier is read–think–write; a correction landing mid-run would be
overwritten by a write based on the stale read. Every classifier write-back
statement carries `WHERE status != 'corrected'` inside one transaction — the
database, never stale, enforces the lock. (Human writes always win; machine
writes defer to the flag.)

## 7. Weekly review and bottlenecks

- Week = Monday–Sunday local. Auto-generated at week end; on demand anytime
(LLM-backed, exempt from the 2s target). Generation runs classification
catch-up first, so the week's final hours are labelled.
- While `work_types` is empty, reviews carry the onboarding nudge instead of a
work-type breakdown.
- **Two-stage ranking.** Stage 1, deterministic SQL — *how big is it*:
score each (project × work type) pair, **[proposed]** `hours × distinct days`, over work blocks only (NULLs excluded). Same data in, same ranking
out; every number auditable against blocks.
- **Shortlist by materiality, not rank:** every pair clearing a floor
(**[proposed]** ≥2h in the week, or ≥30 min on 3+ days), capped at ~15.
Nothing both meaningful and automatable can fall outside it, because
meaningful is the only inclusion criterion.
- **Stage 2, AI judgment — *which are automatable*:** the LLM gets the
shortlist with evidence, selects and orders the 1–3 worth suggesting, and
writes the narrative + each suggestion's evidence/workflow/runnable.
Constraints: no candidates outside the shortlist; every pick cites its
evidence. Stage-1 ranking stored in `reviews.body`; picks become
`suggestions` rows.

## 8. Interfaces

### 8.1 MCP tools (`/mcp`)

Read (bounded; summaries by default, evidence on request):

| Tool | Purpose |
| --- | --- |
| `get_recording_status` | Source freshness, coverage gaps, disk usage; onboarding nudge while `work_types` empty |
| `get_time_breakdown` | Time by project / work type / app / domain / URL; foreground + attended seconds |
| `get_timeline` | A day's blocks in order |
| `list_projects` | Projects with status and totals |
| `get_blocks` | Blocks by range/project, evidence on request |
| `get_weekly_review` | Latest or specified week's review + suggestions |
| `generate_review_now` | On-demand review (slow; runs the LLM) |

Write: `correct_block`, `split_block`, `confirm_project`, `rename_project`,
`merge_projects`, `create_project`, `add_work_type`, `rename_work_type`,
`archive_work_type`. Hard validation (existing ids, known types); returns the
updated object. Tested in Claude (direct) and ChatGPT (Secure MCP Tunnel).

### 8.2 REST (`/api/*`)

Same service layer, ~one route per MCP tool, plus UI needs (screenshot file
serving — localhost only).

### 8.3 Web UI (`/`)

React, static files served by FastAPI. V1 = Brandon's testing/viewing tool:
timeline, breakdowns, project management, block correction, review +
suggestions, recording status, disk usage. Screenshot display in scope;
presentation details later.

### 8.4 Non-functional

- **2s target** for SQLite reads (MCP + UI); LLM-backed actions exempt,
report progress instead.
- **LaunchAgent** starts backend + capture agent at login; immediate
ingest + classification catch-up.
- **Localhost only**, no auth. **Disk usage visible** via status tool + UI.

## 9. Milestones

**Ordering principle (decided):** all ingestion before any intelligence. The
classifier is built once against the full signal set (no prompt rework when
text sources arrive), weeks of rich data accumulate as an evaluation corpus
while the brain is being built, and the scariest risk (TCC under
LaunchAgents) is exercised first, while a pivot would still be cheap. The
accepted cost: the aha moment arrives at M5, not M2 — until then the system
is mechanically useful only (breakdowns, attended time, timeline from
signals). The POC keeps serving AI clients until M6 replaces it. FastAPI's
Swagger UI at `/docs` is the free admin tool from M1 until the React UI.

| # | Milestone | Done when |
| --- | --- | --- |
| **M1** | **Package + store + AW ingest.** Schema, AW adapter (polling + settled-events), `status` CLI, one-time `backfill`. | Fresh install ingests from zero; Brandon's history lands via `backfill`; re-ingest is a no-op; coverage gaps queryable. |
| **M2** | **Capture agent: AX text.** Swift CLI, AX tree capture (caps, hash-skip, secure-field skip, per-call timeouts), spool + `ax-text` adapter. | Real AX text lands in `signals`, cleaned and deduped; a hung app costs one capture, not the agent; spool catches up after backend downtime. |
| **M3** | **Capture agent: screenshots + OCR.** ScreenCaptureKit, perceptual-hash dedup, Vision OCR in-agent, `screenshot` adapter. | OCR text in `signals`; JPEGs on disk within the storage budget; only text ever crosses into Python. |
| **M4** | **Login agents + reliability.** LaunchAgents for backend + capture agent, sleep/crash ingest catch-up, disk usage reporting. | Reboot → both processes resume recording with no manual steps; gaps reported, never guessed. From here, data accumulates unattended. |
| **M5** | **Classification.** Windowing, OpenRouter client, project proposal, block assembly, scheduler + horizon catch-up. | A day of multi-source activity becomes labelled blocks within an hour, idempotently — evaluated against the accumulated corpus. |
| **M6** | **MCP + corrections.** All read/write tools; REST under `/api`; POC deleted. | From Claude and ChatGPT: "anything I need to approve?" answered (proposed projects + work-type nudge), breakdowns/timeline queried, blocks corrected and split, projects and work types managed; corrections survive re-classification. |
| **M7** | **Weekly review.** Two-stage ranking, scheduled + on-demand generation, stored suggestions. | Monday morning: stored review with 1–3 runnable suggestions, same from every client. |
| **M8** | **React UI.** Timeline, breakdowns, editing, review view, status page, screenshot display. | Everything MCP can do, doable in the browser. |
| **M9** | **Early adopters.** Setup docs, rough install script. | A technical friend runs it on their Mac. |

## 10. Open items needing a decision

Each tagged **[proposed]** above where it appears:

1. **Capture agent** (§4.2) — five sub-decisions: screenshot scope (frontmost

   window / active display / all displays), heartbeat cadence (30s vs 60s),
    image budget (~1440px JPEG q60), secure-input skip, same-tick AX +
    screenshot capture.
2. **Bottleneck numbers** (§7): formula `hours × distinct days`; materiality

   floor ≥2h or ≥30min on 3+ days. (Mechanism decided; values not.)
3. **Low-confidence threshold** (§5): default 0.5, configurable.
4. **AW polling interval** (§4.1): 60s.
5. **Partial-week breakdowns**: `get_time_breakdown` over any range suffices —
   confirm no separate tool needed.
6. **Review `body` JSON shape** (§3.4): range / totals / bottlenecks /
   narrative.
7. **`get_weekly_review` default**: serves the week's latest review.
8. **Empty weeks** (§7): still store a review ("no classified work") so a
   missing review always means a bug.
9. **Keep `reviews.trigger`** (the one defensible cut from the final audit;
   recommendation: keep).

Structural-but-unblessed (silence = consent): package layout (§2).

## 11. Decision log

- **2026-11-16 — initial draft:** scope (capture agent and corrections in v1,
one model, full rewrite), architecture, milestones.
- **2026-11-17 — data model:** two-layer `observations` + `signals`
(PK = observation id; wipe-and-rebuild; `extras` write-only); AFK raw-only
with exactly three consumers; foreground **and** attended seconds;
corrections = relabel + split on the 5-minute grid (no drags/merges in v1).
- **2026-11-17 — Layer 2:** `work_types` table with `description` (AI selects,
never invents; user owns the vocabulary); projects / work types / tags meet
only inside blocks; AI-proposed types, consolidation suggestions and
relabel-on-type-change deferred to PRD Later.
- **2026-11-17 — onboarding:** zero-history install assumed everywhere
(backfill = one-time personal convenience); no seed work types —
conversational AI proposal from real data after a day of capture, human
approves, one-time bootstrap re-label; empty `work_types` is the onboarding
state (nudge); no `propose_work_types` endpoint, no day-0 interview.
- **2026-11-17 — final schema audit:** `block_evidence` table dropped
(evidence = derived time-overlap query, view `block_evidence_v`, re-add
trigger documented); `projects.created_by` dropped; `confidence` kept;
settled-events rule (strict insert-only observations); classification
horizon + `classify-backfill`; UTC storage with local week/day boundaries
and clipping; lowercase names and tags; corrected-lock enforced inside
write statements.
- **2026-11-18 — review engine:** two-stage ranking (deterministic
materiality-floor shortlist = "how big"; AI selection = "how automatable",
evidence-cited, no new candidates); catch-up before scoring; block assembly
confirmed; tags uncapped; low-confidence → NULL project; review snapshot
semantics (§3.4).
- **2026-11-18 — milestones:** ingestion-first ordering (M1 AW ingest → M2–M3
capture agent → M4 login agents → M5 classification → M6 MCP → M7 review →
M8 React UI → M9 adopters): classifier built once against the full signal
set, data accumulates as an eval corpus, TCC risk front-loaded; accepted
cost is a later aha moment. Swagger `/docs` is the admin tool until React;
"what needs approval" = `list_projects(status='proposed')` + the work-type
nudge, no new tool. URL layout (`/api` + `/` + `/mcp`) accepted.
