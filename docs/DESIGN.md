# Open Computer History: MVP Design Doc

_Status: draft for review, 2026-11-16; updated 2026-11-17 after the data-model
review (signals layer, AFK handling, corrections scope). Companion to
[PRD.md](PRD.md)._

Sections marked **[proposed]** are my recommendations and still need Brandon's
confirmation. Everything else reflects decisions already made.

---

## 1. Overview

A local macOS system that records computer activity, classifies it into
projects and work types with an LLM, and exposes the result to AI assistants
(via MCP) and a local web UI — ending each week in a review with 1–3 concrete
automation suggestions.

**Decided scope for v1:**

- Capture: ActivityWatch (window, AFK, Chrome) **and** a custom capture agent
  for Accessibility text + screenshots with on-device text recognition.
- Corrections: block corrections and project management are in v1, via MCP
  write tools and the UI. ("Manual corrections" on the Later list means
  corrections-as-rules — generalizing one correction to future classification.)
- One hard-coded OpenRouter model for both block labelling and weekly reviews.
- Full rewrite: a structured Python package replaces `history.py` /
  `history_mcp.py`. The POC is deleted once the new pipeline passes its tests.

**Carried over from the POC's principles:** raw observations immutable, one
service layer for REST/CLI/MCP, bounded purpose-built AI tools, honest coverage
reporting, loopback only, captured text is untrusted data.

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

One FastAPI process hosts the API, MCP and UI, and runs the scheduler.
The capture agent is a separate login-launched process. ActivityWatch is a
separate app, as today.

**[proposed] URL layout:** REST moves under `/api/*`, MCP stays at `/mcp`,
the React UI is served at `/`. This avoids route collisions between React
routes and the POC's root-level REST routes.

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

One SQLite file (e.g. `~/Library/Application Support/ComputerHistory/history.db`).
Screenshots live on disk as files; the DB stores paths and extracted text.

**Time rule (decided):** every stored timestamp is UTC ISO-8601 at uniform
precision, so TEXT comparison works lexicographically. The single exception to
UTC-everywhere: week and day *boundaries* are computed in the user's local
timezone at query/generation time (a UTC week boundary would land mid-Sunday
locally), and blocks spanning a boundary are clipped into each side when
summing.

**Naming rule (decided):** project names, work-type names and tags are
normalized to lowercase (and trimmed) on write, so case variants can never
create duplicates ("YouTube" vs "youtube"). Display casing is a later
nicety.

### 3.1 Layer 1: raw observations (immutable)

The extensibility requirement ("new capture sources plug in without schema
changes") is met by one generic table — a new source is a new `source` value
plus an adapter, not a new table.

```sql
observations (
  id           INTEGER PRIMARY KEY,
  source       TEXT NOT NULL,      -- 'aw-window' | 'aw-afk' | 'aw-web' | 'ax-text' | 'screenshot'
  source_id    TEXT,               -- id in the source system, for dedup on re-ingest
  started_at   TEXT NOT NULL,      -- ISO 8601 UTC
  ended_at     TEXT NOT NULL,
  payload      TEXT NOT NULL,      -- source JSON, verbatim (title, url, app, file path…)
  ingested_at  TEXT NOT NULL,
  UNIQUE (source, source_id)
)
```

Rules: insert-only — no updates, no deletes, no upsert carve-outs (retention
is a later feature). Because some sources grow events in place (ActivityWatch
extends the current window event's duration), adapters follow a
**settled-events rule**: only events that are closed — superseded by a newer
event, or older than a short stability margin — are ingested; the
currently-growing event is simply not ingested yet. Classification runs
hourly, so the few minutes of ingest lag are invisible, and immutability holds
with no exceptions. The original source payload is preserved verbatim;
normalization happens into derived tables, never by editing this row.

### 3.2 Layer 1.5: signals (normalized, rebuildable)

Content sources are projected into one typed table so every consumer reads a
single shape instead of parsing per-source payload JSON. This is where
per-source knowledge is centralized (only adapters know payload dialects), and
normalization here is **computation, not just reshaping**: domain extraction
from URLs and text hygiene (capping, whitespace collapse, dedup against the
previous capture) happen at this step.

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

Rules:

- **1:1 with observations; PK = the observation id.** Signals carry no
  original information, and stable ids make rebuilds invisible to anything
  that references a signal.
- **Written in the same transaction** as their observation, by the adapter —
  drift between the layers can only come from mapping bugs, never crashes.
- **Disposable by design.** `rebuild-signals` (CLI) wipes and re-projects the
  whole table from raw whenever the mapping code improves. No per-row mapping
  version: at this scale a full rebuild takes minutes. A single row in a meta
  table records which code version last built the table.
- **`extras` is write-only.** Consumers may display it (the evidence
  drill-down), never filter or aggregate on it. The moment a query needs a
  field from `extras`, that field is promoted to a real column (ten-second
  migration + `rebuild-signals`).
- **AFK is not in signals.** It is a state, not content — it never describes
  activity, it gates and splits activity from other sources (see §4.3). If a
  second state-like source appears later (screen locked, in a meeting), the
  pattern gets promoted to a `state_spans` table; one instance doesn't justify
  the abstraction.

### 3.3 Layer 2: derived activity

```sql
projects (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,
  status         TEXT NOT NULL,    -- 'proposed' | 'confirmed' | 'archived'
  merged_into_id INTEGER REFERENCES projects(id),  -- set on merge; blocks re-pointed
  created_at     TEXT NOT NULL
)
-- No created_by column: status already carries the provenance that matters
-- (AI-created projects are born 'proposed', user-created ones 'confirmed');
-- after approval, origin changes no behavior, so it isn't stored.

work_types (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT,                -- fed into the classifier prompt; lists the
                                   -- synonyms this type absorbs, e.g.
                                   -- "coding, programming, debugging, DevOps"
  status      TEXT NOT NULL,       -- 'active' | 'archived'
  created_at  TEXT NOT NULL
)

blocks (
  id          INTEGER PRIMARY KEY,
  started_at  TEXT NOT NULL,       -- aligned to 5-minute boundaries
  ended_at    TEXT NOT NULL,
  project_id  INTEGER REFERENCES projects(id),   -- NULL = Unassigned
  work_type_id INTEGER REFERENCES work_types(id),   -- NULL = no type fits / list empty
  confidence  REAL,                -- LLM's 0–1 confidence
  status      TEXT NOT NULL,       -- 'auto' | 'corrected'  (corrected = locked)
  summary     TEXT,                -- one-line LLM description of the block
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
)

block_tags (block_id, tag)         -- optional, search/filter only, never totals
```

Key decisions encoded here:

- A block has **exactly one** project and **one** work type; tags are optional
  and never count toward totals.
- `status = 'corrected'` locks a block: the classifier must never update it.
- Projects are proposed by the AI and label blocks immediately; the user
  confirms, renames, merges, adds. Renames/merges only update references —
  no LLM call. When projects change, **unconfirmed** blocks from the last 14
  days are re-labelled.
- Work types are a user-curated vocabulary: the AI **selects** from the
  active list and never invents new types (can't-fit → low confidence →
  Unassigned, which surfaces as "maybe a work type is missing"). Projects are
  the opposite: an open set the AI proposes freely. The asymmetry is
  deliberate — work types' value is comparability across projects and weeks,
  which LLM-coined near-duplicates ("coding" / "programming") would destroy.
- Projects, work types and tags never reference each other; they meet only
  inside a block. Every cross-question (bottleneck = project × work type) is
  an aggregation over blocks, not a stored relationship.
- **Evidence is a query, not a table** (final-audit decision). A block's
  evidence is exactly the signals whose time range overlaps the block's — one
  indexed range query (kept as a SQL view, `block_evidence_v`, for a stable
  name). Since the classifier reads *all* signals in a window, a stored
  evidence table would cache this query while adding rebuild coordination and
  recompute-on-split machinery for zero information. **Re-add trigger:** the
  moment the classifier starts selecting or weighting signals (e.g. for
  corrections-as-rules), "what the model saw" stops being derivable from time
  overlap and must be stored again. Traceability is unchanged: every label and
  bottleneck claim still drills down to raw signals, per the "honest about
  uncertainty" principle.

#### Projects vs. work types vs. tags

Three independent annotations on a block; they never reference each other and
meet only inside a block row. AI freedom on each axis is inversely
proportional to what breaks when the AI is wrong.

| | **Projects** | **Work types** | **Tags** |
| --- | --- | --- | --- |
| Question answered | *Where did this time go?* (the outcome served) | *What kind of labor was it?* | *What else is worth remembering?* (tools, topics, episodes) |
| Created by | **Both**: AI proposes from activity (`proposed` status, labels blocks immediately); user adds their own | **Human only**: starts empty; user adds — directly, or by asking their AI assistant to propose a list from real activity (it calls `add_work_type`) | **AI, freely**: no vocabulary table exists — tags are just rows on blocks |
| AI's role | Pick an existing project or propose a new one | Select exactly one from the active list; inventing is impossible (strict validation → Unassigned) | Invent liberally (~3/block, normalized lowercase) |
| Human's role | Confirm, rename, merge, archive, add | Own the vocabulary: add, rename, re-describe, archive | Edit per block via `correct_block` |
| How human edits reach the AI | Prompt rebuilt from DB each run; project changes re-label unconfirmed blocks from the last 14 days | Prompt rebuilt each run; `description` teaches which synonyms each type absorbs | n/a — no vocabulary to maintain |
| Vocabulary shape | Open set, grows with your life | Small closed set (~12), curated for comparability | Unbounded free vocabulary |
| In time math | Yes — exactly one per block | Yes — exactly one per block; the bottleneck axis | **Never** — structurally excluded from totals |
| Use cases | "Time by project", project timeline, review grouping | Bottleneck ranking (project × work type), "how much time editing overall" | Search and filter: "when was I in CapCut / working on shorts / editing ep12" |
| Cost of an AI mistake | A duplicate project — one merge fixes it | Would silently split bottleneck math — hence no freedom | A bad tag — worst case a search misses |

**No seed list — AI proposes from real data, human approves (decided).**
`work_types` starts empty, and the design assumes a fresh install with zero
history (backfill is opportunistic, §4.1). The cold-start sequence:

1. **Day 0 (install):** capture starts; that's the only job of day one.
   Classification runs anyway — blocks get projects and tags, with
   `work_type_id = NULL`. Nothing stalls.
2. **Day 1–2:** once real activity has accumulated, the user asks their AI
   assistant to propose a work-type list from it. The proposal is purely
   conversational in v1: the assistant reads activity through the MCP read
   tools, drafts ~8–12 types with descriptions and evidence in chat, and on
   the user's approval creates them via `add_work_type`. No dedicated
   `propose_work_types` endpoint yet.
3. **On first approval (empty → non-empty):** a one-time **bootstrap
   re-label** sweeps the existing auto blocks so the day-0/1 backlog isn't
   permanently typeless. This is a deliberate exception to the deferred
   relabel-on-type-change feature: one trigger, runs once, bounded scope.

The **nudge** is the onboarding mechanism: while `work_types` is empty,
`get_recording_status` and review output include "no work types defined yet —
after a day of activity, ask your assistant to propose a list." It is
meaningless on day 0, actionable on day 2, and persists until acted on; the
empty table *is* the onboarding state, with no wizard or state machine. The
step is skippable — types can be added by hand anytime, and everything but the
work-type axis works without them. (An interview-based day-0 draft — "what
kinds of work fill your week?" — is deliberately not in v1: self-reported
taxonomies are the problem the product exists to correct. It stays in the back
pocket for the non-technical-audience product.)

Blocks with a NULL work type or NULL project are excluded from bottleneck
ranking; a real personal-vs-work distinction is deferred (PRD Later:
"personal vs actual work"). AI-proposed work types during routine
classification and consolidation suggestions also remain deferred (PRD Later
list) — vocabulary proposals happen only in explicit, human-approved flows
like the one above.

### 3.4 Layer 3: reviews and suggestions

Generated and stored by the backend so every AI client sees the same ones.

```sql
reviews (
  id           INTEGER PRIMARY KEY,
  week_start   TEXT NOT NULL,      -- Monday, local time
  trigger      TEXT NOT NULL,      -- 'scheduled' | 'on_demand'
  generated_at TEXT NOT NULL,
  body         TEXT NOT NULL       -- JSON: time by project × work type, bottlenecks w/ evidence
)

suggestions (
  id         INTEGER PRIMARY KEY,
  review_id  INTEGER NOT NULL REFERENCES reviews(id),
  title      TEXT NOT NULL,
  evidence   TEXT NOT NULL,        -- JSON: block ids, hours, recurrence
  workflow   TEXT NOT NULL,        -- the automation, step by step
  runnable   TEXT NOT NULL         -- paste-ready prompt or Claude Code command
)
```

### 3.5 Bookkeeping

```sql
ingest_cursors (source, last_seen)      -- where each adapter resumed from
classification_runs (id, started_at, finished_at, range, model, status, error)
```

`classification_runs` is how catch-up works after sleep: the scheduler
classifies everything between the last successful run and now.

## 4. Ingestion

Each source gets an adapter with the same contract: _pull new data since a
cursor, write `observations` rows plus their `signals` projections in one
transaction, advance the cursor._ Adapters are idempotent (the
`(source, source_id)` unique key makes re-ingest a no-op). Only adapters know
their source's payload shape; everything downstream reads `signals`.

### 4.1 ActivityWatch adapter

- Polls `http://127.0.0.1:5600/api/0` **[proposed]** every 60 seconds for the
  window, AFK, and both Chrome web buckets.
- **No pre-existing history is assumed, anywhere.** A real user's fresh
  install starts from zero; nothing downstream — onboarding included — may
  depend on prior data. Ingesting existing ActivityWatch history is a one-time
  personal convenience for Brandon's own install (about a week of data), done
  in day-sized pages, not a product feature.
- AW events grow in place (the current event's duration extends), so the
  adapter follows the settled-events rule (§3.1): it ingests an event only
  once it is closed — superseded by a newer event or older than a short
  stability margin — keeping observations strictly insert-only.
- Read-only toward ActivityWatch, as today.

### 4.2 Capture agent (Swift) **[proposed: language + mechanics]**

A small Swift CLI launched at login, separate from the Python backend, because
macOS TCC permissions (Accessibility, Screen Recording) attach to a stable
signed binary and the capture + Vision OCR APIs are native.

- **Triggers:** on app/window switch, plus every 30s while active; skips when
  idle (per AW AFK) or screen locked; skips near-identical screenshots.
- **Accessibility text:** focused-window AX tree text, truncated to a cap.
- **Screenshots:** JPEG to disk under the app-support dir; on-device Apple
  Vision OCR; screenshots never leave the Mac — only OCR text is stored in
  `observations.payload` and only text ever reaches the LLM.
- **Handoff:** the agent appends JSONL files (one per hour) to a spool
  directory; the backend's `ax-text` / `screenshot` adapters tail the spool
  like any other source. The agent stays dumb; the backend owns the DB.
  This survives the backend being down (files accumulate, ingest catches up).
- Known risks: Electron/Chrome expose sparse AX trees; macOS re-prompts for
  Screen Recording periodically; TCC under a LaunchAgent is fiddly. Milestones
  6–7 absorb this risk after the core pipeline already works end to end.

### 4.3 AFK: raw-only, three consumers

AFK stays out of `signals` (§3.2). Exactly three places read `aw-afk`
observations directly — each is "give me the AFK intervals for this range,"
which the raw table answers with one trivial query:

1. **Classifier windowing:** fully-AFK 5-minute windows are skipped — no
   digest, no LLM call, no block.
2. **Block assembly:** AFK gaps over 5 minutes split blocks, so a long break
   separates two work blocks instead of being welded into one.
3. **Time breakdowns:** attended time = signal intervals ∩ not-afk intervals
   (the same clip-and-merge interval math the POC already uses). Breakdown
   responses report both `foreground_seconds` and `attended_seconds`.

Two semantics pinned down:

- **Missing AFK data is a coverage gap, never attendance.** Window events
  with no AFK stream (watcher off, permission revoked) → return foreground
  time with a coverage warning; never silently equate "no AFK data" with
  "attended the whole time."
- **AFK undercounts passive consumption** (watching a video without input
  reads as AFK). Accepted for v1; attended time slightly undercounts.

## 5. Classification: from observations to blocks

Runs on a schedule inside the backend (freshness target: within ~1 hour).
The AI client never classifies on the fly; it reads stored results.

1. **Windowing.** Slice un-classified time into fixed 5-minute windows
   (decided). For each window, assemble a text digest from `signals`:
   apps + titles with durations, domains/URLs, cleaned AX / OCR text
   (capped). Windows that are fully AFK (per raw `aw-afk`, §4.3) are skipped.
2. **LLM labelling.** Batch N windows per call to OpenRouter (one hard-coded
   model, text only). The prompt includes the current project list (names +
   one-line descriptions) and the active work-type list (names + descriptions
   — the description tells the model which synonyms each type absorbs, so
   "programming" and "DevOps" land in "software engineering" if that's how the
   user sliced it). The model returns,
   per window: project (existing, or a proposed new one), work type (selected
   from the list, never invented), up to 3 tags **[proposed]**, confidence,
   one-line summary. The prompt also states what a project is (an outcome
   being worked toward, never a kind of activity — "Video Editing" is a work
   type, not a project).
3. **Project proposal.** A new project name in the response creates a
   `proposed` project row immediately and labels the window with it (decided).
4. **Block assembly [proposed].** Merge consecutive windows with the same
   (project, work type) into one block; split at AFK gaps over 5 minutes.
5. **Write-back.** Insert blocks with `status='auto'`. Never touch
   `corrected` blocks. Low-confidence windows get `project_id = NULL`
   (Unassigned) rather than a guess **[proposed]**; likewise
   `work_type_id = NULL` when no active type fits or the list is still empty.
6. **Catch-up, with a horizon.** On startup (login agent) and after sleep,
   classify the gap since the last successful `classification_run` — capped by
   a classification horizon (default 14 days back, configurable). Anything
   older is ingested and mechanically queryable (breakdowns read signals), but
   is only classified by an explicit `classify-backfill` command, so a large
   first ingest can never trigger a surprise LLM burn.

**Prompt-injection posture (deferred, by decision):** titles, URLs, AX text
and OCR text flow into the classifier prompt. V1 only constrains the output
(strict JSON schema, project/work-type values validated against known lists);
hardening is on the Later list.

## 6. Projects and corrections

| Action | Effect |
| --- | --- |
| Confirm project | `status → confirmed`. |
| Rename project | Update `name`; references untouched; no LLM call. |
| Merge A into B | `A.merged_into_id = B`, A archived; A's blocks re-pointed to B; no LLM call. |
| Add project | New `confirmed` row, `created_by='user'`; appears in the next classifier prompt. |
| Add / rename / re-describe / archive a work type | Rename is reference surgery; description edits steer the next classifier run; archive hides it from the prompt without touching old blocks. Adding a type affects future classification only (re-labelling recent blocks on type changes is deferred — PRD Later), with one exception: the first empty → non-empty transition triggers the one-time bootstrap re-label (§3.3). |
| Correct a block | Set project / work type / tags; `status → 'corrected'` (locked forever). |
| Split a block | `split_block(block_id, at_time)`, snapped to the 5-minute grid. Evidence is a time-range query, so each half's evidence follows automatically; halves are then correctable independently. |
| Project set changes | Re-label **unconfirmed** blocks from the last 14 days (decided). |

**Scope of time edits in v1: splitting only.** A split subdivides what a block
already owns, so the rest of the timeline is untouched — no neighbor
conflicts, no gap-filling policy. Dragging boundaries and merging neighbors
change the partitioning of the day (every moved edge forces a decision about
the adjacent block) and wait until there's evidence they're needed; the
classifier already splits at AFK gaps and label changes, which catches most
real transitions. Users edit interpretation only: nothing ever writes to
`observations` or `signals`.

Corrections fix only that block in v1; corrections-as-rules are later.
All of the above is available from both MCP write tools and the UI, through
the same service layer.

**The lock is enforced in the write statement, not at read time.** The
classifier is a read–think–write pipeline; a correction can land between its
read and its write, and a write based on the stale read would overwrite the
correction. So the classifier's write-back guards every statement
(`... WHERE status != 'corrected'`, inside one transaction) — the database,
whose knowledge is never stale, enforces the lock, and a correction made
mid-run survives.

## 7. Weekly review and bottlenecks

- Week = Monday–Sunday, local time. Generated automatically when the week
  ends and on demand anytime (on-demand runs are allowed to exceed the
  2-second target since they call the LLM).
- While `work_types` is empty, reviews carry the onboarding nudge (§3.3) in
  place of a work-type breakdown.
- **Ranking is deterministic, in the backend** (decided): score each
  (project × work type) pair — **[proposed] formula:** `hours × distinct days
  it recurs`, over confirmed-work blocks only (no `personal`, no Unassigned).
- The LLM then takes the top-ranked pairs **with evidence blocks** and writes
  the review narrative plus 1–3 suggestions, each with: evidence, a workflow,
  and a ready-to-run prompt or Claude Code command. Stored in
  `reviews` / `suggestions` so Claude, ChatGPT and the UI all see the same.

## 8. Interfaces

### 8.1 MCP tools (`/mcp`)

Read (bounded, summaries by default, evidence on request — as in the POC):

| Tool | Purpose |
| --- | --- |
| `get_recording_status` | Source freshness, coverage gaps, disk usage; onboarding nudge while `work_types` is empty |
| `get_time_breakdown` | Time by project / work type / app / domain / URL over a range; reports both foreground and attended seconds |
| `get_timeline` | A day's blocks in order |
| `list_projects` | Projects with status and totals |
| `get_blocks` | Blocks filtered by range/project, with evidence on request |
| `get_weekly_review` | Latest or specified week's review + suggestions |
| `generate_review_now` | On-demand review (slow; runs the LLM) |

Write (the correction/project actions from §6):

`correct_block`, `split_block`, `confirm_project`, `rename_project`,
`merge_projects`, `create_project`, `add_work_type`, `rename_work_type`,
`archive_work_type`.

Writes validate hard (existing ids, known work types) and return the updated
object. Tested in both Claude (direct) and ChatGPT (Secure MCP Tunnel).

### 8.2 REST (`/api/*`)

Same service layer, roughly one route per MCP tool, plus what the UI needs
(e.g. screenshot file serving for the UI's evidence view — localhost only).

### 8.3 Web UI (`/`)

React, built to static files, served by FastAPI. V1 is Brandon's testing and
viewing tool: daily timeline, breakdowns, project management, block
correction, weekly review + suggestions, recording status, disk usage.
Screenshot display is in scope; presentation details decided later.

### 8.4 Non-functional handling

- **2-second target** applies to reads from SQLite (MCP + UI). LLM-backed
  actions (on-demand review, backfill classification) are exempt and report
  progress instead.
- **Login agent:** a LaunchAgent starts the backend (and capture agent) at
  login; the backend immediately runs ingest + classification catch-up.
- **Localhost only**, no auth, same posture as the POC.
- **Disk usage visible** via `get_recording_status` and the UI.

## 9. Milestones

Each milestone is independently useful and testable before the next starts.
The POC keeps running until M3, when the new system replaces it.

| # | Milestone | Done when |
| --- | --- | --- |
| **M1** | **Package + store + AW ingest.** New package, SQLite schema, ActivityWatch adapter with full backfill and polling, `status`/`backfill` CLI. | All AW history is in `observations`; re-running ingest is a no-op; coverage gaps queryable. |
| **M2** | **Classification.** Windowing, OpenRouter client, project proposal, block assembly, scheduler with catch-up. | A day of real activity becomes labelled blocks within an hour, idempotently. |
| **M3** | **MCP + corrections.** All read and write tools; REST under `/api`; POC deleted. | From Claude and ChatGPT: query timeline/breakdowns, correct a block, manage projects; corrected blocks survive re-classification. |
| **M4** | **Weekly review.** Ranking, review generation (scheduled + on demand), suggestions stored. | Monday morning: a stored review with 1–3 runnable suggestions, same from every client. |
| **M5** | **React UI.** Timeline, breakdowns, project/block editing, review view, status page. | Brandon can do everything from the browser that MCP can do. |
| **M6** | **Login agent + reliability.** LaunchAgent, sleep/crash catch-up, disk usage reporting. | Reboot the Mac; recording and classification resume with no manual steps. |
| **M7** | **Capture agent: Accessibility text.** Swift agent, spool handoff, `ax-text` adapter, text feeding classification. | Blocks from AX-rich apps get visibly better labels. |
| **M8** | **Capture agent: screenshots + OCR.** Screen capture, dedup, Vision OCR, UI screenshot display. | OCR text improves classification; screenshots viewable in the UI; nothing but text leaves the Mac. |
| **M9** | **Early adopters.** Setup docs, rough install script, a second Mac runs it. | A technical friend is running it on their machine. |

## 10. Open items to settle as we go

Carried from discussion, each tagged **[proposed]** above where it appears:

1. Work-type list contents (§3.2)
2. Tags: LLM assigns up to 3, user-editable (§5)
3. Block assembly: merge-same-label, split at >5-min AFK gaps (§5)
4. Low-confidence → Unassigned, excluded from ranking (§5, §7)
5. Bottleneck formula: hours × recurring days (§7)
6. Capture agent: Swift, triggers, spool handoff, ~200–500 MB/day estimate (§4.2)
7. URL layout `/api` + `/` + `/mcp` (§2)
8. AW polling interval (§4.1)
9. Partial-week on-demand breakdowns: covered by `get_time_breakdown` over any range, so no separate tool — confirm this is enough

**Settled in the 2026-11-17 data-model review** (reflected above): two-layer
observations + signals; signals PK = observation id; full wipe-and-rebuild
(`rebuild-signals`) instead of per-row mapping versions; `extras` write-only;
AFK raw-only with exactly three consumers; breakdowns report foreground and
attended seconds; corrections = relabel + split on the 5-minute grid, with no
boundary drags or merges in v1.

**Settled in the Layer 2 review (also 2026-11-17):** `work_types` is a
user-curated table seeded on first run — the AI selects from it and never
invents types, the user adds/renames/archives (AI-proposed types and
consolidation suggestions deferred to PRD Later, as is re-labelling on
work-type changes); projects / work types / tags never reference each other
and meet only inside blocks; block evidence was first keyed to signals, then
dropped as a table entirely in the final audit (below) — it is a derived
time-overlap query. Work types carry a `description` fed into
the classifier prompt, which is where the user teaches the model which
synonyms each type absorbs. `work_types` starts empty (no seed list);
`blocks.work_type_id` is nullable, and cold start is the user asking their AI
assistant to propose types from real activity via `add_work_type`.

**Settled in the onboarding review (also 2026-11-17):** backfill is
opportunistic, never assumed — all flows must work from a zero-history fresh
install; work-type onboarding = capture first, AI proposes conversationally
from real data after a day or two, human approves, then a one-time bootstrap
re-label heals the typeless backlog; the empty `work_types` table is the
onboarding state, surfaced as a nudge in `get_recording_status` and reviews;
no `propose_work_types` endpoint and no day-0 interview in v1.

**Settled in the final schema audit (2026-11-17):** `block_evidence` dropped —
evidence is a derived time-overlap query over signals (kept as a view,
`block_evidence_v`), with a documented re-add trigger if the classifier ever
selects/weights signals; `projects.created_by` dropped (status carries the
provenance that matters); `blocks.confidence` kept; observations strictly
insert-only via the settled-events rule (no upsert carve-out); classification
horizon (default 14 days) caps catch-up, with `classify-backfill` for older
history; all stored timestamps UTC (week/day boundaries converted to local at
query time, boundary-spanning blocks clipped); project/work-type names and
tags lowercased on write; the corrected-block lock enforced inside the
classifier's write statements.
