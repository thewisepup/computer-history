"""A digest of what the database holds, for checking that two builds stored the same thing."""

from __future__ import annotations

import hashlib
import json
import sqlite3

_CONTENTS = (
    "SELECT source, source_id, started_at, ended_at, payload FROM observations"
    " ORDER BY source, source_id",
    "SELECT o.source, o.source_id, s.source, s.started_at, s.ended_at, s.app, s.domain, s.url,"
    " s.title, s.text, s.extras FROM signals AS s JOIN observations AS o ON o.id = s.observation_id"
    " ORDER BY o.source, o.source_id",
    "SELECT source, position, settled_until FROM ingest_progress ORDER BY source",
)


def content_digest(conn: sqlite3.Connection) -> str:
    """A hash of the observations, signals and ingest progress, each in a fixed order."""
    digest = hashlib.sha256()
    for query in _CONTENTS:
        digest.update(b"\x00table\n")
        for row in conn.execute(query):
            digest.update(json.dumps(list(row), ensure_ascii=False).encode() + b"\n")
    return digest.hexdigest()
