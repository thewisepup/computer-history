from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import urlopen

import pytest
from aw_http import aw_server, served_over_http

from computer_history.sources import (
    AX_TEXT_SOURCE,
    DEFAULT_AW_URL,
    AWClient,
    AWError,
)
from computer_history.store import connect, content_digest, get_progress, utc_iso
from computer_history.synthetic import SCENARIOS, Dataset, DatasetInputs, build_dataset
from computer_history.synthetic.activitywatch import ActivityWatchRenderer
from computer_history.synthetic.aw_api import ServedAW
from computer_history.synthetic.spool import RENDERED_SPOOL_FOLDER

REPO = Path(__file__).resolve().parent.parent
CLI = Path(sys.executable).with_name("computer-history")
LIVE_AW_PORT = urlparse(DEFAULT_AW_URL).port
DEVELOPER_DAY = DatasetInputs(persona="developer", scenario="typical", tier="day", seed=1)


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_the_real_cli_over_http_stores_what_the_in_process_build_stores(
    tmp_path: Path, scenario: str
) -> None:
    inputs = DatasetInputs(persona="developer", scenario=scenario, tier="day", seed=1)
    dataset = build_dataset(inputs, tmp_path / "in-process")
    spool = tmp_path / "cli" / "spool"
    shutil.copytree(dataset.db_path.parent / RENDERED_SPOOL_FOLDER, spool)
    db_path = tmp_path / "cli" / "history.db"

    started = datetime.now(UTC)
    with served_over_http(_served(dataset)) as url:
        _run_cli(tmp_path, "--db-path", db_path, "backfill", "--aw-url", url)
        _run_cli(tmp_path, "--db-path", db_path, "ingest", "--aw-url", url, "--spool-path", spool)
    finished = datetime.now(UTC)

    in_process, cli = connect(dataset.db_path), connect(db_path)
    try:
        assert content_digest(cli, progress=False) == content_digest(in_process, progress=False)
        assert _progress(cli, AX_TEXT_SOURCE) == _progress(in_process, AX_TEXT_SOURCE)
        for stream in ActivityWatchRenderer.streams:
            assert _progress(in_process, stream) == (utc_iso(dataset.now), dataset.now)
            position, settled = _progress(cli, stream)
            assert settled is not None, stream
            assert started <= settled <= finished, stream
            assert position == utc_iso(settled), stream
    finally:
        in_process.close()
        cli.close()
    assert list(spool.glob("*.jsonl")) == []


def test_the_http_server_answers_as_the_in_process_api(tmp_path: Path) -> None:
    served = _served(build_dataset(DEVELOPER_DAY, tmp_path / "day"))

    with served_over_http(served) as url:
        client = AWClient(url)
        assert client.get_buckets() == served.get_buckets()
        for bucket, events in served.events.items():
            middle = events[len(events) // 2]
            inside = middle.start + (middle.end - middle.start) / 2
            bounds = (None, events[0].start, inside, middle.end, events[-1].end)
            for start in bounds:
                for end in bounds:
                    if start is not None and end is not None and end <= start:
                        continue
                    for limit in (-1, 0, 1, 5):
                        query = {"start": start, "end": end, "limit": limit}
                        got = client.get_events(bucket, **query)
                        assert got == served.get_events(bucket, **query), (bucket, query)
            for event in (events[0], middle, events[-1]):
                assert client.get_event(bucket, event.id) == served.get_event(bucket, event.id)
            assert client.get_event(bucket, events[-1].id + 1) is None
        with pytest.raises(AWError, match="404"):
            client.get_events("no-such-bucket")
        naive = f"{url}/buckets/{next(iter(served.events))}/events?start=2026-01-05T09:00:00"
        with pytest.raises(HTTPError) as refused:
            urlopen(naive)
        assert refused.value.code == 400


def test_the_http_server_binds_only_loopback_on_an_ephemeral_port(tmp_path: Path) -> None:
    served = _served(build_dataset(DEVELOPER_DAY, tmp_path / "day"))

    server = aw_server(served)
    try:
        bound_host, bound_port = server.socket.getsockname()[:2]
    finally:
        server.server_close()
    with served_over_http(served) as first, served_over_http(served) as second:
        hosts = {bound_host, urlparse(first).hostname, urlparse(second).hostname}
        ports = {bound_port, urlparse(first).port, urlparse(second).port}

    assert hosts == {"127.0.0.1"}
    assert len(ports) == 3 and LIVE_AW_PORT not in ports


def _served(dataset: Dataset) -> ServedAW:
    rendered = dataset.rendered[ActivityWatchRenderer.name]
    return ServedAW(rendered.buckets, rendered.events)


def _progress(conn: sqlite3.Connection, stream: str) -> tuple[str, datetime | None]:
    progress = get_progress(conn, stream)
    assert progress is not None, stream
    return progress.position, progress.settled_until


def _run_cli(tmp_path: Path, *args: object) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPUTER_HISTORY_")}
    env["HOME"] = str(tmp_path / "home")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH")]))
    run = subprocess.run(
        [CLI, *map(str, args)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=timedelta(minutes=5).total_seconds(),
    )
    assert run.returncode == 0, f"{args}\n{run.stdout}\n{run.stderr}"
    return run.stdout
