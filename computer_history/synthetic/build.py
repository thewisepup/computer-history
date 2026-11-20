"""Build a dataset: render every source, then ingest it through the real backfill and poll."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from computer_history.sources import (
    STABILITY_MARGIN_SECONDS,
    plan_all_backfills,
    poll,
    run_backfill,
)
from computer_history.store import connect, content_digest
from computer_history.synthetic.activitywatch import ActivityWatchRenderer
from computer_history.synthetic.generate import DatasetInputs, generate_timeline
from computer_history.synthetic.manifest import Manifest, true_answers
from computer_history.synthetic.renderer import Feed, RenderedSource, Renderer
from computer_history.synthetic.timeline import Timeline, part_random

RENDERERS: tuple[Renderer, ...] = (ActivityWatchRenderer(),)
SETTLE_AFTER = timedelta(seconds=STABILITY_MARGIN_SECONDS + 60)
DATABASE_NAME = "history.db"
MANIFEST_NAME = "manifest.json"


class BuildFailed(RuntimeError):
    """Ingest could not read the rendered data into the dataset's database."""


@dataclass(frozen=True)
class Dataset:
    """A built dataset: its database and manifest files, and what they were made from.

    The feeds read the rendered data again, as of the fixed now the build ingested at.
    """

    db_path: Path
    manifest_path: Path
    timeline: Timeline
    rendered: Mapping[str, RenderedSource]
    feeds: tuple[Feed, ...]
    manifest: Manifest
    now: datetime


def build_dataset(inputs: DatasetInputs, folder: Path) -> Dataset:
    """Generate, render and ingest the dataset into a new database in the folder, with its manifest.

    The same inputs always give the same database contents.
    """
    folder.mkdir(parents=True, exist_ok=True)
    db_path, manifest_path = folder / DATABASE_NAME, folder / MANIFEST_NAME
    if db_path.exists():
        raise FileExistsError(f"{db_path} already exists")
    timeline = generate_timeline(inputs)
    rendered = {
        renderer.name: renderer.render(timeline, part_random(inputs.seed, renderer.name))
        for renderer in RENDERERS
    }
    feeds = tuple(source.feed(folder) for source in rendered.values())
    now = timeline.end + SETTLE_AFTER
    conn = connect(db_path)
    try:
        backfill_feeds(conn, feeds, start=timeline.start, now=now)
        poll_feeds(conn, feeds, now=now)
        digest = content_digest(conn)
    finally:
        conn.close()
    manifest = true_answers(inputs, timeline, rendered.values(), digest)
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    return Dataset(db_path, manifest_path, timeline, rendered, feeds, manifest, now)


def backfill_feeds(
    conn: sqlite3.Connection, feeds: Sequence[Feed], *, start: datetime, now: datetime
) -> int:
    """Backfill each stream of the feeds that keep history from the start; returns rows inserted."""
    inserted = 0
    for feed in feeds:
        if feed.history is None:
            continue
        planning = plan_all_backfills(conn, feed.history, now=now, start=start)
        if planning.failure is not None:
            raise BuildFailed(f"planning the backfill failed: {planning.failure.error}")
        run = run_backfill(conn, feed.history, planning.plans, clock=lambda: now)
        if not run.ok:
            raise BuildFailed(f"the backfill failed: {run.failure}")
        inserted += sum(result.inserted for result in run.results)
    return inserted


def poll_feeds(conn: sqlite3.Connection, feeds: Sequence[Feed], *, now: datetime) -> int:
    """Poll every stream of the feeds until none has more; returns rows inserted."""
    summary = poll(conn, [feed.source for feed in feeds], now=now)
    if not summary.ok:
        raise BuildFailed(f"polling failed: {summary.failures}")
    return sum(outcome.inserted for outcome in summary.outcomes.values())
