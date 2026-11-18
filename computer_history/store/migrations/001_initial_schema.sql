-- All timestamps are UTC ISO-8601 text.

-- Layer 1: raw observations (immutable, insert-only).
CREATE TABLE observations (
  id           INTEGER PRIMARY KEY,
  source       TEXT NOT NULL,      -- 'aw-window' | 'aw-afk' | 'aw-web' | 'ax-text' | 'screenshot'
  source_id    TEXT,
  started_at   TEXT NOT NULL,
  ended_at     TEXT NOT NULL,
  payload      TEXT NOT NULL,
  ingested_at  TEXT NOT NULL,
  UNIQUE (source, source_id)
);

CREATE INDEX observations_source_started_at ON observations (source, started_at);

-- Layer 1.5: normalized signals (rebuildable; 1:1 with content observations).
CREATE TABLE signals (
  observation_id INTEGER PRIMARY KEY REFERENCES observations (id),
  source      TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  ended_at    TEXT NOT NULL,
  app         TEXT,
  domain      TEXT,
  url         TEXT,
  title       TEXT,
  text        TEXT,
  extras      TEXT
);

CREATE INDEX signals_started_at ON signals (started_at);

-- Layer 2: derived activity.
CREATE TABLE projects (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,
  status         TEXT NOT NULL,    -- 'proposed' | 'confirmed' | 'archived'
  merged_into_id INTEGER REFERENCES projects (id),
  created_at     TEXT NOT NULL
);

CREATE TABLE work_types (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT,
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
  summary      TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE INDEX blocks_started_at ON blocks (started_at);

CREATE TABLE block_tags (
  block_id INTEGER NOT NULL REFERENCES blocks (id) ON DELETE CASCADE,
  tag      TEXT NOT NULL,
  PRIMARY KEY (block_id, tag)
);

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

-- Layer 3: reviews and suggestions (snapshots, never overwritten).
CREATE TABLE reviews (
  id           INTEGER PRIMARY KEY,
  week_start   TEXT NOT NULL,      -- Monday, local time
  trigger      TEXT NOT NULL,      -- 'scheduled' | 'on_demand'
  generated_at TEXT NOT NULL,
  body         TEXT NOT NULL
);

CREATE TABLE suggestions (
  id         INTEGER PRIMARY KEY,
  review_id  INTEGER NOT NULL REFERENCES reviews (id),
  title      TEXT NOT NULL,
  evidence   TEXT NOT NULL,
  workflow   TEXT NOT NULL,
  runnable   TEXT NOT NULL
);

-- Bookkeeping.
CREATE TABLE ingest_cursors (
  source    TEXT PRIMARY KEY,
  last_seen TEXT NOT NULL
);

CREATE TABLE classification_runs (
  id          INTEGER PRIMARY KEY,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  range_start TEXT NOT NULL,
  range_end   TEXT NOT NULL,
  model       TEXT NOT NULL,
  status      TEXT NOT NULL,
  error       TEXT
);
