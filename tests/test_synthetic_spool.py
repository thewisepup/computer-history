from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from computer_history.sources import AX_TEXT_SOURCE, day_counts, parse_record, stored_records
from computer_history.sources.ax_text.spool import FINISHED_NAME_FORMAT
from computer_history.store import connect, content_digest, payload_values, source_summary
from computer_history.synthetic import (
    CaptureCounts,
    DatasetInputs,
    Stretch,
    StretchKind,
    Timeline,
    build_dataset,
    build_timeline,
    generate_timeline,
    poll_feeds,
)
from computer_history.synthetic import build as synthetic_build
from computer_history.synthetic.activitywatch import ActivityWatchRenderer
from computer_history.synthetic.captures import IDLE_THRESHOLD
from computer_history.synthetic.spool import (
    BUNDLE_IDS,
    SPOOL_FOLDER,
    TEXT_CAP_BYTES,
    SpoolRenderer,
)
from computer_history.synthetic.timeline import PRECISION

DAY = datetime(2026, 1, 5, tzinfo=UTC)
PR = "https://github.com/acme/computer-history/pulls"
LONG_PAGE = "x" * 60_000


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return DAY + timedelta(hours=hour, minutes=minute, seconds=second)


SPOOL_HAND_WORKED = Timeline(
    at(9, 0),
    at(9, 10),
    "UTC",
    (
        Stretch(at(9, 0), at(9, 1, 10), app="Cursor", title="spool.py — computer-history"),
        Stretch(at(9, 1, 10), at(9, 2), app="Cursor", title="runner.py — computer-history"),
        Stretch(
            at(9, 2),
            at(9, 6, 30),
            app="Google Chrome",
            title="Pull requests",
            url=PR,
            text=LONG_PAGE,
            afk=True,
        ),
        Stretch(at(9, 6, 30), at(9, 10), kind=StretchKind.ASLEEP),
    ),
)
SPOOL_HAND_WORKED_CAPTURES = CaptureCounts(
    kinds={"capture": 11},
    triggers={"app": 1, "heartbeat": 9, "title": 1},
    apps={"Cursor": 5, "Google Chrome": 6},
)
SPOOL_HAND_WORKED_TIMES = [
    (at(9, 0, 1), "Cursor"),
    (at(9, 0, 31), "Cursor"),
    (at(9, 1, 1), "Cursor"),
    (at(9, 1, 11), "Cursor"),
    (at(9, 1, 41), "Cursor"),
    (at(9, 2, 1), "Google Chrome"),
    (at(9, 2, 31), "Google Chrome"),
    (at(9, 3, 1), "Google Chrome"),
    (at(9, 3, 31), "Google Chrome"),
    (at(9, 4, 1), "Google Chrome"),
    (at(9, 4, 31), "Google Chrome"),
]
SPOOL_HAND_WORKED_FILES = {
    "20260105T090100.000Z.jsonl": 2,
    "20260105T090200.000Z.jsonl": 3,
    "20260105T090300.000Z.jsonl": 2,
    "20260105T090400.000Z.jsonl": 2,
    "20260105T090500.000Z.jsonl": 2,
}


@pytest.fixture
def plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        synthetic_build,
        "RENDERERS",
        (ActivityWatchRenderer(), SpoolRenderer(hostile_windows_per_day=0)),
    )


def test_a_hand_worked_capture_session_reports_the_records_worked_out_by_hand(
    tmp_path: Path, plain_text: None
) -> None:
    dataset = build_timeline(SPOOL_HAND_WORKED, tmp_path / "session", seed=1)
    conn = connect(dataset.db_path)
    try:
        records = stored_records(conn, SPOOL_HAND_WORKED.start, SPOOL_HAND_WORKED.end)
        values = payload_values(
            conn,
            AX_TEXT_SOURCE,
            SPOOL_HAND_WORKED.start,
            SPOOL_HAND_WORKED.end,
            ("$.trigger", "$.full_text_bytes", "$.text"),
        )
        counts = {row.source: row.observation_count for row in source_summary(conn)}
    finally:
        conn.close()
    files = sorted((dataset.db_path.parent / SPOOL_FOLDER).iterdir())

    assert dataset.manifest.captures == SPOOL_HAND_WORKED_CAPTURES
    assert dataset.manifest.observations == {
        "aw-afk": 2,
        "aw-web": 1,
        "aw-window": 3,
        "ax-text": 11,
    }
    assert counts == dataset.manifest.observations
    assert [(r.at, r.app) for r in records] == SPOOL_HAND_WORKED_TIMES
    assert Counter(row.values[0] for row in values) == SPOOL_HAND_WORKED_CAPTURES.triggers
    assert day_counts(records, SPOOL_HAND_WORKED.start).cut_off == 6
    assert [(row.values[1], len(row.values[2].encode())) for row in values[5:]] == (
        [(60_000, 50_000)] * 6
    )
    assert {f.name: len(f.read_bytes().split(b"\n")) - 1 for f in files} == (
        SPOOL_HAND_WORKED_FILES
    )


REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "fixtures" / "spool" / "records.jsonl"
DEVELOPER_DAY = DatasetInputs(persona="developer", scenario="typical", tier="day", seed=1)
AGENT_NAME = re.compile(r"\d{8}T\d{6}\.\d{3}Z\.jsonl")


def _fixture_lines() -> list[str]:
    return FIXTURE.read_bytes().decode("utf-8").split("\n")[:-1]


def _spool_lines(folder: Path) -> list[tuple[Path, str]]:
    return [
        (path, line)
        for path in sorted(folder.iterdir())
        for line in path.read_bytes().decode("utf-8").split("\n")[:-1]
    ]


def _encoded_like_the_agent(line: str) -> str:
    return json.dumps(json.loads(line), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def test_every_rendered_line_parses_and_matches_the_fixture_format(tmp_path: Path) -> None:
    dataset = build_dataset(DEVELOPER_DAY, tmp_path / "day")
    fixture = {parse_record(line).kind: line for line in _fixture_lines()}
    capture_keys = set(json.loads(fixture["capture"]))
    lines = _spool_lines(dataset.db_path.parent / SPOOL_FOLDER)

    assert all(_encoded_like_the_agent(line) == line for line in fixture.values())
    assert len(lines) == dataset.manifest.observations["ax-text"] > 0
    previous = None
    for path, line in lines:
        record = parse_record(line)
        finished = datetime.strptime(path.stem, FINISHED_NAME_FORMAT).replace(tzinfo=UTC)
        assert AGENT_NAME.fullmatch(path.name), path.name
        assert record.kind == "capture", line[:200]
        assert set(record.fields) == capture_keys, line[:200]
        assert _encoded_like_the_agent(line) == line, line[:200]
        assert record.fields["text_sha256"] == sha256(record.fields["text"].encode()).hexdigest()
        assert len(record.fields["text"].encode()) <= TEXT_CAP_BYTES
        assert record.captured_at < finished, (path.name, line[:200])
        assert previous is None or record.captured_at > previous
        previous = record.captured_at


def _stretch_at(timeline: Timeline, moment: datetime) -> Stretch:
    index = bisect_right([s.start for s in timeline.stretches], moment) - 1
    return timeline.stretches[index]


def test_stored_captures_equal_the_manifest_and_fall_in_their_apps_stretches(
    tmp_path: Path,
) -> None:
    dataset = build_dataset(DEVELOPER_DAY, tmp_path / "day")
    start, end = dataset.timeline.start, dataset.timeline.end
    conn = connect(dataset.db_path)
    try:
        records = stored_records(conn, start, end)
        values = payload_values(conn, AX_TEXT_SOURCE, start, end, ("$.trigger", "$.window_title"))
        counts = {row.source: row.observation_count for row in source_summary(conn)}
    finally:
        conn.close()
    stored = CaptureCounts(
        kinds=dict(sorted(Counter(r.kind for r in records).items())),
        triggers=dict(sorted(Counter(row.values[0] for row in values).items())),
        apps=dict(sorted(Counter(r.app for r in records).items())),
    )

    assert stored == dataset.manifest.captures
    assert counts["ax-text"] == sum(dataset.manifest.captures.kinds.values())
    assert set(stored.triggers) == {"app", "window", "title", "heartbeat"}
    for record, row in zip(records, values, strict=True):
        stretch = _stretch_at(dataset.timeline, record.at)
        assert stretch.active and (record.app, row.values[1]) == (stretch.app, stretch.title)


def test_the_rendered_spool_survives_ingest_and_ingesting_it_again_adds_nothing(
    tmp_path: Path,
) -> None:
    dataset = build_dataset(DEVELOPER_DAY, tmp_path / "day")
    folder = dataset.db_path.parent
    built = sorted(path.name for path in folder.iterdir())
    rendered = dataset.rendered[SpoolRenderer.name]
    on_disk = {path.name: path.read_bytes() for path in (folder / SPOOL_FOLDER).iterdir()}
    conn = connect(dataset.db_path)
    try:
        again = poll_feeds(conn, [rendered.feed(folder)], now=dataset.now)
        digest = content_digest(conn)
    finally:
        conn.close()

    assert built == ["history.db", "manifest.json", SPOOL_FOLDER]
    assert on_disk == {
        file.name: "".join(f"{line}\n" for line in file.lines).encode() for file in rendered.files
    }
    assert again == 0
    assert digest == dataset.manifest.content_digest


def t(minute: int, second: float = 0) -> datetime:
    return at(10, minute) + timedelta(milliseconds=round(second * 1000))


def _render(*stretches: Stretch) -> list[tuple[datetime, str, str, str]]:
    timeline = Timeline(stretches[0].start, stretches[-1].end, "UTC", stretches)
    rendered = SpoolRenderer(hostile_windows_per_day=0).render(timeline, random.Random(0))
    return [
        (
            record.captured_at,
            record.fields["trigger"],
            record.fields["app_name"],
            record.fields["window_title"],
        )
        for file in rendered.files
        for record in map(parse_record, file.lines)
    ]


def _files(*stretches: Stretch) -> dict[str, int]:
    timeline = Timeline(stretches[0].start, stretches[-1].end, "UTC", stretches)
    rendered = SpoolRenderer(hostile_windows_per_day=0).render(timeline, random.Random(0))
    return {file.name: len(file.lines) for file in rendered.files}


def test_a_burst_of_switches_captures_the_final_state_once_with_the_strongest_trigger() -> None:
    assert _render(
        Stretch(t(0), t(0, 40), app="Cursor", title="a.py"),
        Stretch(t(0, 40), t(0, 40.5), app="Cursor", title="b.py"),
        Stretch(t(0, 40.5), t(2), app="Terminal", title="zsh"),
    ) == [
        (t(0, 1), "heartbeat", "Cursor", "a.py"),
        (t(0, 31), "heartbeat", "Cursor", "a.py"),
        (t(0, 41.5), "app", "Terminal", "zsh"),
        (t(1, 11.5), "heartbeat", "Terminal", "zsh"),
        (t(1, 41.5), "heartbeat", "Terminal", "zsh"),
    ]


def test_a_title_that_never_settles_is_captured_one_heartbeat_after_it_first_changed() -> None:
    flicker = [
        Stretch(t(0, 10 + k / 2), t(0, 10.5 + k / 2), app="Google Chrome", title=f"t{k}")
        for k in range(80)
    ]
    assert _render(
        Stretch(t(0), t(0, 10), app="Google Chrome", title="start"),
        *flicker,
        Stretch(t(0, 50), t(1, 30), app="Google Chrome", title="final"),
    ) == [
        (t(0, 1), "heartbeat", "Google Chrome", "start"),
        (t(0, 40), "title", "Google Chrome", "t60"),
        (t(0, 51), "title", "Google Chrome", "final"),
        (t(1, 21), "heartbeat", "Google Chrome", "final"),
    ]


def test_another_project_in_the_same_app_is_a_window_change() -> None:
    assert _render(
        Stretch(t(0), t(0, 10), app="Cursor", title="a.py", project="one"),
        Stretch(t(0, 10), t(0, 20), app="Cursor", title="a.py", project="two"),
    ) == [
        (t(0, 1), "heartbeat", "Cursor", "a.py"),
        (t(0, 11), "window", "Cursor", "a.py"),
    ]


SLEEPY = (
    Stretch(t(0), t(0, 45), app="Cursor", title="a.py"),
    Stretch(t(0, 45), t(5, 20), kind=StretchKind.ASLEEP),
    Stretch(t(5, 20), t(6, 10), app="Cursor", title="a.py"),
    Stretch(t(6, 10), t(7), kind=StretchKind.ASLEEP),
    Stretch(t(7), t(7, 40), app="Notion", title="plan"),
)


def test_nothing_is_captured_asleep_and_waking_captures_a_second_later() -> None:
    assert _render(*SLEEPY) == [
        (t(0, 1), "heartbeat", "Cursor", "a.py"),
        (t(0, 31), "heartbeat", "Cursor", "a.py"),
        (t(5, 21), "heartbeat", "Cursor", "a.py"),
        (t(5, 51), "heartbeat", "Cursor", "a.py"),
        (t(7, 1), "app", "Notion", "plan"),
        (t(7, 31), "heartbeat", "Notion", "plan"),
    ]


def test_a_minute_that_ends_asleep_is_finished_on_waking() -> None:
    assert _files(*SLEEPY) == {
        "20260105T100520.000Z.jsonl": 2,
        "20260105T100600.000Z.jsonl": 2,
        "20260105T100800.000Z.jsonl": 2,
    }


def test_captures_stop_once_the_user_is_idle_and_resume_a_second_after_they_return() -> None:
    captured = _render(
        Stretch(t(0), t(1, 1), app="Terminal", title="zsh"),
        Stretch(t(1, 1), t(3), app="Terminal", title="zsh", afk=True),
        Stretch(t(3), t(6), app="Terminal", title="zsh", afk=True),
        Stretch(t(6), t(7), app="Terminal", title="zsh"),
    )

    assert [moment for moment, *_ in captured] == [
        *(t(0, 1) + k * timedelta(seconds=30) for k in range(9)),
        t(6, 1),
        t(6, 31),
    ]


@pytest.mark.parametrize(
    ("text", "kept"),
    [("é" * 30_000, "é" * 25_000), ("a" + "🙂" * 12_500, "a" + "🙂" * 12_499)],
    ids=["two-byte", "four-byte"],
)
def test_text_past_the_cap_is_cut_on_a_character_and_the_cut_off_recorded(
    text: str, kept: str
) -> None:
    timeline = Timeline(
        t(0), t(0, 10), "UTC", (Stretch(t(0), t(0, 10), app="Notes", title="n", text=text),)
    )
    rendered = SpoolRenderer(hostile_windows_per_day=0).render(timeline, random.Random(0))
    record = parse_record(rendered.files[0].lines[0]).fields

    assert (record["text"], record["full_text_bytes"], record["text_cut_off"]) == (
        kept,
        len(text.encode()),
        True,
    )


def test_a_developer_day_stores_hostile_titles_and_text_as_captured(tmp_path: Path) -> None:
    dataset = build_dataset(DEVELOPER_DAY, tmp_path / "day")
    start, end = dataset.timeline.start, dataset.timeline.end
    conn = connect(dataset.db_path)
    try:
        rows = payload_values(
            conn, AX_TEXT_SOURCE, start, end, ("$.window_title", "$.text", "$.text_cut_off")
        )
    finally:
        conn.close()
    titles = [row.values[0] for row in rows]
    texts = [row.values[1] for row in rows]

    assert any("Ignore all previous instructions" in title for title in titles)
    assert any("SYSTEM: ignore all previous instructions" in text for text in texts)
    assert any("\u202egnirts desrever\u202c" in text and "\u2028" in text for text in texts)
    assert any(row.values[2] for row in rows)


SPOOL_IN_A_NEW_PROCESS = """
import sys
from pathlib import Path
from computer_history.synthetic import DatasetInputs, build_dataset
inputs = DatasetInputs(persona="developer", scenario="typical", tier="day", seed=1)
dataset = build_dataset(inputs, Path(sys.argv[1]))
print(dataset.manifest.content_digest, end="")
"""


def _spool_digest(folder: Path) -> str:
    digest = sha256()
    for path in sorted((folder / SPOOL_FOLDER).iterdir()):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def test_separate_processes_render_the_same_spool_and_digest(tmp_path: Path) -> None:
    built = {}
    for hash_seed, timezone in (("0", "UTC"), ("4242", "Asia/Kolkata")):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "TZ": timezone}
        folder = tmp_path / hash_seed
        run = subprocess.run(
            [sys.executable, "-c", SPOOL_IN_A_NEW_PROCESS, str(folder)],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        built[hash_seed] = (run.stdout, _spool_digest(folder))
    here = build_dataset(DEVELOPER_DAY, tmp_path / "here")

    assert (
        built["0"]
        == built["4242"]
        == (
            here.manifest.content_digest,
            _spool_digest(tmp_path / "here"),
        )
    )


AGENT_ENV_VAR = "CAPTURE_AGENT_BINARY"
TICK = timedelta(milliseconds=500)
AGENT_READ_LAG = timedelta(milliseconds=100)


def _on_ticks(timeline: Timeline) -> Timeline:
    def tick(moment: datetime) -> datetime:
        return timeline.start + -((timeline.start - moment) // TICK) * TICK

    stretches = []
    for stretch in timeline.stretches:
        start, end = tick(stretch.start), tick(stretch.end)
        if end > start:
            stretches.append(replace(stretch, start=start, end=end))
    return Timeline(timeline.start, tick(timeline.end), "UTC", tuple(stretches))


def _script(timeline: Timeline) -> dict:
    def offset(moment: datetime) -> float:
        return (moment - timeline.start) / timedelta(seconds=1)

    def app_id(app: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "-", app)

    apps: dict[str, dict] = {}
    steps: list[dict] = []
    titles: dict[tuple[str, str], str] = {}
    focused: dict[str, str] = {}
    front: str | None = None
    away_since: datetime | None = None
    for stretch in timeline.stretches:
        at_ = offset(stretch.start)
        if not stretch.active:
            steps.append({"at": at_, "presence": {"asleep": True}})
            away_since = None
            continue
        if not stretch.afk or away_since is None:
            steps.append({"at": at_, "presence": {}})
        app, window = app_id(stretch.app), app_id(stretch.project or "none")
        spec = apps.setdefault(
            app,
            {"name": stretch.app, "bundle_id": BUNDLE_IDS.get(stretch.app), "windows": {}},
        )
        spec["windows"].setdefault(window, {"role": "AXWindow", "title": stretch.title})
        spec.setdefault("focused_window", window)
        titles.setdefault((app, window), stretch.title)
        focused.setdefault(app, window)
        if titles[(app, window)] != stretch.title:
            change = {"app": app, "window": window, "title": stretch.title}
            steps.append({"at": at_, "set_title": change})
            titles[(app, window)] = stretch.title
        if focused[app] != window:
            steps.append({"at": at_, "focus_window": {"app": app, "window": window}})
            focused[app] = window
        if front != app:
            steps.append({"at": at_, "focus": app})
            front = app
        if stretch.afk:
            away_since = away_since or stretch.start
            idle = away_since + IDLE_THRESHOLD + PRECISION
            if stretch.start <= idle < stretch.end:
                idle_seconds = IDLE_THRESHOLD.total_seconds() + 1
                steps.append({"at": offset(idle), "presence": {"idle_seconds": idle_seconds}})
        else:
            away_since = None
    steps.append({"at": offset(timeline.end), "end": True})
    start = timeline.start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"start": start, "apps": apps, "steps": steps}


def _records(lines: Iterable[str]) -> list[tuple]:
    return [
        (
            r.captured_at,
            *(r.fields[k] for k in ("trigger", "app_name", "bundle_id", "window_title")),
        )
        for r in map(parse_record, lines)
    ]


@pytest.mark.skipif(
    not os.environ.get(AGENT_ENV_VAR),
    reason=f"needs the built capture agent in ${AGENT_ENV_VAR}; run capture-agent/scripts/e2e.sh",
)
def test_the_rendered_captures_match_the_real_agent_playing_the_same_day(tmp_path: Path) -> None:
    timeline = _on_ticks(generate_timeline(DEVELOPER_DAY))
    script = tmp_path / "day.json"
    script.write_text(json.dumps(_script(timeline)), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPUTER_HISTORY_")}
    env["COMPUTER_HISTORY_DB"] = str(tmp_path / "agent" / "history.db")
    (tmp_path / "agent").mkdir()
    run = subprocess.run(
        [os.environ[AGENT_ENV_VAR], "scripted-session", str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    agent = _records(line for _, line in _spool_lines(tmp_path / "agent" / "spool"))
    rendered = SpoolRenderer(hostile_windows_per_day=0).render(timeline, random.Random(0))
    ours = _records(line for file in rendered.files for line in file.lines)

    assert len(ours) > 1000
    assert [r[1:] for r in agent] == [r[1:] for r in ours]
    lag = [theirs[0] - mine[0] for theirs, mine in zip(agent, ours, strict=True)]
    assert all(timedelta(0) <= late < AGENT_READ_LAG for late in lag), max(lag)
