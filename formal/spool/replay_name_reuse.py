"""Replay the two_ingests counterexample on the real CaptureSpool, commit_pull and store.

Run: PYTHONPATH=. .venv/bin/python formal/spool/replay_name_reuse.py
Prints "record lost: True" while the finding stands.
"""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from computer_history.sources import (
    SCREENSHOT_SOURCE,
    WINDOW_TEXT_SOURCE,
    CaptureSpool,
    commit_pull,
    projector_for,
)
from computer_history.store import connect

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "spool" / "records.jsonl"
NAME = "20261118T090100.000Z.jsonl"
NOW = datetime(2026, 11, 18, 10, tzinfo=UTC)


def line(n: int) -> str:
    lines = FIXTURE.read_text().splitlines()
    data = next(d for d in map(json.loads, lines) if d["kind"] == "capture")
    data["id"] = f"00000000-0000-4000-8000-{n:012x}"
    return json.dumps(data, sort_keys=True)


def main() -> None:
    root = Path(tempfile.mkdtemp())
    spool = root / "spool"
    spool.mkdir()
    conn = connect(root / "history.db")

    (spool / NAME).write_text(line(2) + "\n")  # the agent finishes record 2, then crashes
    first, second = CaptureSpool(spool), CaptureSpool(spool)
    project = projector_for([first])
    streams = (WINDOW_TEXT_SOURCE, SCREENSHOT_SOURCE)
    early = [first.pull_after(s, None, now=NOW) for s in streams]  # both ingests read the file
    late = [second.pull_after(s, None, now=NOW) for s in streams]
    for stream, pulled in zip(streams, late, strict=True):
        commit_pull(conn, stream, pulled, project=project, now=NOW, progress_from=pulled)
    (spool / NAME).write_text(line(1) + "\n")  # restarted, clock set back: same name, record 1
    for stream, pulled in zip(streams, early, strict=True):
        commit_pull(conn, stream, pulled, project=project, now=NOW, progress_from=pulled)

    stored = {row[0] for row in conn.execute("SELECT source_id FROM observations")}
    lost = json.loads(line(1))["id"] not in stored and not (spool / NAME).exists()
    print("stored:", sorted(stored))
    print("spool files left:", sorted(p.name for p in spool.iterdir()))
    print("record lost:", lost)


if __name__ == "__main__":
    main()
