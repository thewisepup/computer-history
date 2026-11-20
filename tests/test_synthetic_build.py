from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from store_answers import stored_days, stored_totals

from computer_history.sources import Pull, reproject_signals
from computer_history.store import connect, content_digest, source_summary
from computer_history.synthetic import (
    HEAVY,
    DatasetInputs,
    Stretch,
    StretchKind,
    Timeline,
    Totals,
    backfill_feeds,
    build_dataset,
    build_timeline,
    poll_feeds,
)
from computer_history.synthetic import build as synthetic_build
from computer_history.synthetic.renderer import Feed

REPO = Path(__file__).resolve().parent.parent

DEVELOPER_DAY = DatasetInputs(persona="developer", scenario="typical", tier="day", seed=1)


def test_the_same_inputs_build_the_same_dataset(tmp_path: Path) -> None:
    first = build_dataset(DEVELOPER_DAY, tmp_path / "first")
    second = build_dataset(DEVELOPER_DAY, tmp_path / "second")

    assert first.timeline == second.timeline
    assert first.rendered == second.rendered
    assert first.manifest.content_digest == second.manifest.content_digest
    assert first.manifest == second.manifest


def test_another_seed_builds_a_different_dataset(tmp_path: Path) -> None:
    first = build_dataset(DEVELOPER_DAY, tmp_path / "first")
    other = build_dataset(
        DatasetInputs(persona="developer", scenario="typical", tier="day", seed=2),
        tmp_path / "other",
    )

    assert first.manifest.content_digest != other.manifest.content_digest


def test_stored_time_equals_the_manifest(tmp_path: Path) -> None:
    dataset = build_dataset(DEVELOPER_DAY, tmp_path / "day")
    manifest = dataset.manifest
    conn = connect(dataset.db_path)
    try:
        stored = stored_totals(conn, manifest.start, manifest.end)
        days = stored_days(conn, manifest)
        counts = {row.source: row.observation_count for row in source_summary(conn)}
    finally:
        conn.close()

    assert stored == manifest.total
    assert days == manifest.days
    assert counts == manifest.observations
    assert manifest.total.foreground_app_seconds and manifest.total.afk_seconds > 0


def test_ingesting_the_dataset_again_adds_nothing(tmp_path: Path) -> None:
    dataset = build_dataset(DEVELOPER_DAY, tmp_path / "day")
    conn = connect(dataset.db_path)
    try:
        polled = poll_feeds(conn, dataset.feeds, now=dataset.now)
        backfilled = backfill_feeds(
            conn, dataset.feeds, start=dataset.timeline.start, now=dataset.now
        )
        digest = content_digest(conn)
    finally:
        conn.close()

    assert (polled, backfilled) == (0, 0)
    assert digest == dataset.manifest.content_digest


def test_rebuilding_signals_gives_the_same_signals(tmp_path: Path) -> None:
    dataset = build_dataset(DEVELOPER_DAY, tmp_path / "day")
    conn = connect(dataset.db_path)
    try:
        rebuilt = reproject_signals(conn)
        digest = content_digest(conn)
    finally:
        conn.close()

    assert rebuilt.signals_before == rebuilt.signals_after > 0
    assert digest == dataset.manifest.content_digest


def at(hour: int, minute: int) -> datetime:
    return DAY + timedelta(hours=hour, minutes=minute)


DAY = datetime(2026, 1, 5, tzinfo=UTC)
PR = "https://github.com/acme/ledger/pull/1"
HAND_WORKED = Timeline(
    DAY,
    DAY + timedelta(days=1),
    "UTC",
    (
        Stretch(DAY, at(9, 0), kind=StretchKind.ASLEEP),
        Stretch(at(9, 0), at(9, 12), app="Cursor", title="a.py"),
        Stretch(at(9, 12), at(9, 15), app="Cursor", title="a.py", afk=True),
        Stretch(at(9, 15), at(9, 20), app="Cursor", title="a.py"),
        Stretch(at(9, 20), at(9, 30), app="Google Chrome", title="Pull #1", url=PR),
        Stretch(at(9, 30), DAY + timedelta(days=1), kind=StretchKind.ASLEEP),
    ),
)
HAND_WORKED_TOTALS = Totals(
    foreground_app_seconds={"Cursor": 1200.0, "Google Chrome": 600.0},
    foreground_domain_seconds={"github.com": 600.0},
    attended_app_seconds={"Cursor": 1019.999, "Google Chrome": 600.0},
    afk_seconds=179.999,
)


def test_a_hand_worked_morning_reports_the_numbers_worked_out_by_hand(tmp_path: Path) -> None:
    dataset = build_timeline(HAND_WORKED, tmp_path / "morning", seed=1)
    conn = connect(dataset.db_path)
    try:
        stored = stored_totals(conn, HAND_WORKED.start, HAND_WORKED.end)
        counts = {row.source: row.observation_count for row in source_summary(conn)}
    finally:
        conn.close()

    assert dataset.manifest.total == HAND_WORKED_TOTALS
    assert dataset.manifest.days == {"2026-01-05": HAND_WORKED_TOTALS}
    assert stored == HAND_WORKED_TOTALS
    assert dataset.manifest.observations == {"aw-afk": 3, "aw-web": 1, "aw-window": 2}
    assert counts == {"aw-afk": 3, "aw-web": 1, "aw-window": 2}


BUILD_IN_A_NEW_PROCESS = """
import sys
from pathlib import Path
from computer_history.synthetic import DatasetInputs, build_dataset
persona, tier, heavy, folder = sys.argv[1:]
inputs = DatasetInputs(persona=persona, scenario="typical", tier=tier, seed=1, heavy=float(heavy))
print(build_dataset(inputs, Path(folder)).manifest_path.read_text(), end="")
"""


@pytest.mark.parametrize(
    "inputs",
    [
        DEVELOPER_DAY,
        DatasetInputs(persona="developer", scenario="typical", tier="day", seed=1, heavy=HEAVY),
        DatasetInputs(persona="content-creator", scenario="typical", tier="week", seed=1),
    ],
    ids=["developer-day", "heavy-developer-day", "content-creator-week"],
)
def test_separate_processes_with_other_hash_seeds_and_timezones_build_the_same_dataset(
    inputs: DatasetInputs, tmp_path: Path
) -> None:
    manifests = []
    for hash_seed, timezone in (("0", "UTC"), ("4242", "Asia/Kolkata")):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "TZ": timezone}
        folder = tmp_path / f"{hash_seed}-{timezone.replace('/', '-')}"
        argv = [inputs.persona, inputs.tier, str(inputs.heavy), str(folder)]
        built = subprocess.run(
            [sys.executable, "-c", BUILD_IN_A_NEW_PROCESS, *argv],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        manifests.append(json.loads(built.stdout))
    here = json.loads(build_dataset(inputs, tmp_path / "here").manifest_path.read_text())

    assert manifests[0] == manifests[1] == here


class _NoStreams:
    projectors: dict = {}

    def streams(self) -> list[str]:
        return []

    def pull_after(self, stream: str, position: str | None, *, now: datetime) -> Pull:
        raise AssertionError("a source with no streams is never pulled")


@dataclass(frozen=True)
class _Draws:
    values: tuple[float, ...]

    def observation_counts(self) -> dict[str, int]:
        return {}

    def feed(self, folder: Path) -> Feed:
        return Feed(_NoStreams())


class _NoisyRenderer:
    name = "noisy"
    streams = ()

    def render(self, timeline: Timeline, rng: random.Random) -> _Draws:
        return _Draws(tuple(rng.random() for _ in range(1000)))


def test_a_new_renderer_does_not_change_what_the_others_produce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = build_dataset(DEVELOPER_DAY, tmp_path / "before")
    monkeypatch.setattr(
        synthetic_build, "RENDERERS", (_NoisyRenderer(), *synthetic_build.RENDERERS)
    )
    after = build_dataset(DEVELOPER_DAY, tmp_path / "after")

    assert after.timeline == before.timeline
    assert after.rendered["activitywatch"] == before.rendered["activitywatch"]
    assert after.manifest.content_digest == before.manifest.content_digest
