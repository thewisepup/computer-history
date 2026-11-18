-- 001: the complete docs/DESIGN.md §3 data model.
--
-- Timestamps are UTC ISO-8601 TEXT with uniform precision, so string comparison
-- is chronological (block_evidence_v and every range query rely on this).
-- Status/source values are documented, not CHECK-constrained: SQLite cannot alter
-- a CHECK without rebuilding the table, and new sources must not need a migration.
-- No BEGIN/COMMIT here: the migration runner wraps this file in one transaction.

-- §3.1 Layer 1: raw, immutable, insert-only.
CREATE TABLE observations (
  id           INTEGER PRIMARY KEY,
  source       TEXT NOT NULL,      -- 'aw-window' | 'aw-afk' | 'aw-web' | 'ax-text' | 'screenshot'
  source_id    TEXT,               -- id in the source system; dedup on re-ingest
  started_at   TEXT NOT NULL,
  ended_at     TEXT NOT NULL,
  payload      TEXT NOT NULL,      -- source JSON, verbatim
  ingested_at  TEXT NOT NULL,
  UNIQUE (source, source_id)
);

CREATE INDEX observations_source_started_at ON observations (source, started_at);

-- §3.2 Layer 1.5: normalized, rebuildable; 1:1 with content observations (no AFK).
CREATE TABLE signals (
  observation_id INTEGER PRIMARY KEY REFERENCES observations (id),
  source      TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  ended_at    TEXT NOT NULL,
  app         TEXT,             -- from aw-window
  domain      TEXT,             -- extracted from url (the "time by site" unit)
  url         TEXT,             -- from aw-web
  title       TEXT,
  text        TEXT,             -- AX / OCR text, cleaned and capped
  extras      TEXT              -- leftover source-specific fields, JSON; display only
);

CREATE INDEX signals_started_at ON signals (started_at);

-- The mapping code version the current signals rows were built with. One row at most.
CREATE TABLE signals_meta (
  id              INTEGER PRIMARY KEY CHECK (id = 1),
  mapping_version INTEGER NOT NULL
);

-- §3.3 Layer 2: derived activity.
CREATE TABLE projects (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,
  status         TEXT NOT NULL,    -- 'proposed' | 'confirmed' | 'archived'
  merged_into_id INTEGER REFERENCES projects (id),  -- merge tombstone
  created_at     TEXT NOT NULL
);

CREATE TABLE work_types (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT,                -- in classifier prompt: synonyms this type absorbs
  status      TEXT NOT NULL,       -- 'active' | 'archived'
  created_at  TEXT NOT NULL
);

CREATE TABLE blocks (
  id           INTEGER PRIMARY KEY,
  started_at   TEXT NOT NULL,      -- 5-minute aligned
  ended_at     TEXT NOT NULL,
  project_id   INTEGER REFERENCES projects (id),     -- NULL = Unassigned
  work_type_id INTEGER REFERENCES work_types (id),   -- NULL = no fit / list empty
  confidence   REAL,
  status       TEXT NOT NULL,      -- 'auto' | 'corrected' (corrected = locked)
  summary      TEXT,               -- one-line LLM description
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE INDEX blocks_started_at ON blocks (started_at);

-- Search/filter only, never totals. Tags belong to their block.
CREATE TABLE block_tags (
  block_id INTEGER NOT NULL REFERENCES blocks (id) ON DELETE CASCADE,
  tag      TEXT NOT NULL,
  PRIMARY KEY (block_id, tag)
);

-- Evidence is a query, not a table: signals overlapping the block's
-- [started_at, ended_at). A zero-length signal counts if its instant falls in
-- the range (including exactly at started_at).
CREATE VIEW block_evidence_v AS
SELECT
  b.id AS block_id,
  s.observation_id,
  s.source,
  s.started_at,
  s.ended_at,
  s.app,
  s.domain,
  s.url,
  s.title,
  s.text,
  s.extras
FROM blocks AS b
JOIN signals AS s
  ON s.started_at < b.ended_at
 AND (s.ended_at > b.started_at OR s.started_at = b.started_at);

-- §3.4 Layer 3: reviews and suggestions (snapshots, never overwritten).
CREATE TABLE reviews (
  id           INTEGER PRIMARY KEY,
  week_start   TEXT NOT NULL,      -- Monday, local time
  trigger      TEXT NOT NULL,      -- 'scheduled' | 'on_demand'
  generated_at TEXT NOT NULL,
  body         TEXT NOT NULL       -- JSON: range, totals, bottlenecks + evidence, narrative
);

CREATE TABLE suggestions (
  id         INTEGER PRIMARY KEY,
  review_id  INTEGER NOT NULL REFERENCES reviews (id),
  title      TEXT NOT NULL,
  evidence   TEXT NOT NULL,        -- JSON: block ids, hours, recurrence (display-only)
  workflow   TEXT NOT NULL,        -- the automation, for a human to judge
  runnable   TEXT NOT NULL         -- paste-ready prompt or Claude Code command
);

-- §3.5 Bookkeeping: two independent frontiers (ingested vs. classified time).
CREATE TABLE ingest_cursors (
  source    TEXT PRIMARY KEY,
  last_seen TEXT NOT NULL          -- per-source ingestion frontier
);

-- Doubles as the LLM audit log. The classified range is two columns (not one
-- 'range' value) so the classified-time frontier is a plain MAX(range_end).
CREATE TABLE classification_runs (
  id          INTEGER PRIMARY KEY,
  started_at  TEXT NOT NULL,
  finished_at TEXT,                -- NULL while running
  range_start TEXT NOT NULL,
  range_end   TEXT NOT NULL,
  model       TEXT NOT NULL,
  status      TEXT NOT NULL,
  error       TEXT
);
