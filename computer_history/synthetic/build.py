"""Build a dataset: render every source, then ingest it through the real backfill and poll."""

from __future__ import annotations

import shutil
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
from computer_history.store import DATABASE_NAME, connect, content_digest
from computer_history.synthetic.activitywatch import ActivityWatchRenderer
from computer_history.synthetic.generate import DatasetInputs, generate_timeline
from computer_history.synthetic.manifest import Manifest, true_answers
from computer_history.synthetic.renderer import Feed, RenderedSource, Renderer
from computer_history.synthetic.seeds import part_random
from computer_history.synthetic.spool import INGEST_FOLDER, SpoolRenderer
from computer_history.synthetic.timeline import Timeline

RENDERERS: tuple[Renderer, ...] = (ActivityWatchRenderer(), SpoolRenderer())
SETTLE_AFTER = timedelta(seconds=STABILITY_MARGIN_SECONDS + 60)
MANIFEST_NAME = "manifest.json"
SIDECARS = ("-wal", "-shm", "-journal")


class BuildFailed(RuntimeError):
    """Ingest could not read the rendered data into the dataset's database."""


@dataclass(frozen=True)
class Dataset:
    """A built dataset: its database and manifest files, and what they were made from."""

    db_path: Path
    manifest_path: Path
    timeline: Timeline
    rendered: Mapping[str, RenderedSource]
    feeds: tuple[Feed, ...]
    manifest: Manifest
    now: datetime


def build_dataset(inputs: DatasetInputs, folder: Path) -> Dataset:
    """Generate, render and ingest the dataset into a new database in the folder, with its manifest.

    A build that fails leaves no database behind.
    """
    return build_timeline(generate_timeline(inputs), folder, seed=inputs.seed, inputs=inputs)


def build_timeline(
    timeline: Timeline, folder: Path, *, seed: int, inputs: DatasetInputs | None = None
) -> Dataset:
    """Render and ingest a given timeline as build_dataset does, recording the inputs if any."""
    folder.mkdir(parents=True, exist_ok=True)
    db_path, manifest_path = folder / DATABASE_NAME, folder / MANIFEST_NAME
    if db_path.exists():
        raise FileExistsError(f"{db_path} already exists")
    rendered = render_sources(timeline, seed)
    feeds = tuple(source.feed(folder) for source in rendered.values())
    now = timeline.end + SETTLE_AFTER
    try:
        conn = connect(db_path)
        try:
            backfill_feeds(conn, feeds, start=timeline.start, now=now)
            poll_feeds(conn, feeds, now=now)
            digest = content_digest(conn)
        finally:
            conn.close()
        manifest = true_answers(inputs, timeline, rendered.values(), digest)
        manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    except BaseException:
        for leftover in (db_path, manifest_path, *_sidecars(db_path)):
            leftover.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(folder / INGEST_FOLDER, ignore_errors=True)
    return Dataset(db_path, manifest_path, timeline, rendered, feeds, manifest, now)


def render_sources(timeline: Timeline, seed: int) -> dict[str, RenderedSource]:
    """Every renderer's raw data for the timeline, by renderer name."""
    return {
        renderer.name: renderer.render(timeline, part_random(seed, renderer.name))
        for renderer in RENDERERS
    }


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


def _sidecars(db_path: Path) -> tuple[Path, ...]:
    return tuple(db_path.with_name(db_path.name + suffix) for suffix in SIDECARS)
