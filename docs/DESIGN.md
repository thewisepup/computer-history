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

Rules: insert-only. Never updated, never deleted (retention is a later
feature). The original source payload is preserved verbatim; normalization
happens at read time or into derived tables, never by editing this row.

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
  original information, and stable ids mean rebuilds can never dangle
  `block_evidence` links or corrected blocks.
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
  created_by     TEXT NOT NULL,    -- 'ai' | 'user'
  created_at     TEXT NOT NULL
)

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
  work_type_id INTEGER NOT NULL REFERENCES work_types(id),
  confidence  REAL,                -- LLM's 0–1 confidence
  status      TEXT NOT NULL,       -- 'auto' | 'corrected'  (corrected = locked)
  summary     TEXT,                -- one-line LLM description of the block
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
)

block_tags (block_id, tag)         -- optional, search/filter only, never totals

block_evidence (block_id, signal_id)  -- signals supporting the label; signal id = observation id; derived, recomputable
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
- `block_evidence` gives every label and every bottleneck claim traceable
  evidence, per the "honest about uncertainty" principle. Its FK targets
  `signals` (what the classifier actually read); because signal ids are
  observation ids, `rebuild-signals` re-creates identical keys — the rebuild
  runs as one transaction with deferred FK checks, so evidence never dangles.
  Membership is derived from time overlap, so it is recomputed
  deterministically when a block is split.

#### Projects vs. work types vs. tags

Three independent annotations on a block; they never reference each other and
meet only inside a block row. AI freedom on each axis is inversely
proportional to what breaks when the AI is wrong.

| | **Projects** | **Work types** | **Tags** |
| --- | --- | --- | --- |
| Question answered | *Where did this time go?* (the outcome served) | *What kind of labor was it?* | *What else is worth remembering?* (tools, topics, episodes) |
| Created by | **Both**: AI proposes from activity (`proposed` status, labels blocks immediately); user adds their own | **Human only**: seeded on first run, then user adds | **AI, freely**: no vocabulary table exists — tags are just rows on blocks |
| AI's role | Pick an existing project or propose a new one | Select exactly one from the active list; inventing is impossible (strict validation → Unassigned) | Invent liberally (~3/block, normalized lowercase) |
| Human's role | Confirm, rename, merge, archive, add | Own the vocabulary: add, rename, re-describe, archive | Edit per block via `correct_block` |
| How human edits reach the AI | Prompt rebuilt from DB each run; project changes re-label unconfirmed blocks from the last 14 days | Prompt rebuilt each run; `description` teaches which synonyms each type absorbs | n/a — no vocabulary to maintain |
| Vocabulary shape | Open set, grows with your life | Small closed set (~12), curated for comparability | Unbounded free vocabulary |
| In time math | Yes — exactly one per block | Yes — exactly one per block; the bottleneck axis | **Never** — structurally excluded from totals |
| Use cases | "Time by project", project timeline, review grouping | Bottleneck ranking (project × work type), "how much time editing overall" | Search and filter: "when was I in CapCut / working on shorts / editing ep12" |
| Cost of an AI mistake | A duplicate project — one merge fixes it | Would silently split bottleneck math — hence no freedom | A bad tag — worst case a search misses |

**[proposed] Seed work-type list** (inserted into `work_types` on first run;
user adds/renames/archives from there): coding, code review, debugging,
deploying/ops, design, research, writing/scripting, video editing,
communication, meetings, planning/admin, learning, personal.
`personal` blocks and `project_id = NULL` blocks are excluded from bottleneck
ranking (only real work matters). AI-proposed work types and consolidation
suggestions are deferred (PRD Later list).

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
- **First run backfills all existing ActivityWatch history** (decided), in
  day-sized pages so it doesn't hold everything in memory.
- AW events can grow in place (the current event's duration extends), so the
  adapter re-reads a small trailing overlap window and upserts by `source_id`.
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
   (Unassigned) rather than a guess **[proposed]**.
6. **Catch-up.** On startup (login agent) and after sleep, classify the whole
   gap since the last successful `classification_run`.

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
| Add / rename / re-describe / archive a work type | Rename is reference surgery; description edits steer the next classifier run; archive hides it from the prompt without touching old blocks. Adding a type affects future classification only (re-labelling recent blocks on type changes is deferred — PRD Later). |
| Correct a block | Set project / work type / tags; `status → 'corrected'` (locked forever). |
| Split a block | `split_block(block_id, at_time)`, snapped to the 5-minute grid. Each half gets its evidence recomputed from its time range; halves are then correctable independently. |
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

## 7. Weekly review and bottlenecks

- Week = Monday–Sunday, local time. Generated automatically when the week
  ends and on demand anytime (on-demand runs are allowed to exceed the
  2-second target since they call the LLM).
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
| `get_recording_status` | Source freshness, coverage gaps, disk usage |
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
and meet only inside blocks; `block_evidence` FK targets `signals`
(signal id = observation id), with `rebuild-signals` running as one
transaction with deferred FK checks. Work types carry a `description` fed into
the classifier prompt, which is where the user teaches the model which
synonyms each type absorbs.
