CREATE TABLE ingest_progress (
  source        TEXT PRIMARY KEY,
  position      TEXT NOT NULL,     -- source-defined: a timestamp, 'file:offset', ...
  settled_until TEXT,              -- NULL = the source does not say
  advanced_at   TEXT NOT NULL
);

INSERT INTO ingest_progress (source, position, settled_until, advanced_at)
SELECT source, last_seen, last_seen, last_seen FROM ingest_cursors;

DROP TABLE ingest_cursors;
