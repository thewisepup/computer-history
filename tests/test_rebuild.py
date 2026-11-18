"""rebuild-signals tests: wipe the signals table and re-project from raw observations."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fake_aw import FakeAW, at
from projectors import AW

from computer_history import cli
from computer_history.sources import (
    AFK_SOURCE,
    WEB_SOURCE,
    WINDOW_SOURCE,
    ActivityWatch,
    poll,
)
from computer_history.store import (
    RebuildAborted,
    connect,
    rebuild_signals,
    transaction,
)
from computer_history.store import signals as signals_module

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
AFK_BUCKET = "aw-watcher-afk_test-host.local"
WEB_BUCKET = "aw-watcher-web-chrome_test-host.local"


def fixture_aw() -> FakeAW:
    """Window, AFK and web events exercising every normalization path."""
    fake = FakeAW(
        {WINDOW_BUCKET: "currentwindow", AFK_BUCKET: "afkstatus", WEB_BUCKET: "web.tab.current"}
    )
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "Code", "title": "  a.py\t— repo  "})
    fake.add(WINDOW_BUCKET, 1, 60, {"app": "Google Chrome", "title": "GitHub", "extra": 3})
    fake.add(WINDOW_BUCKET, 2, 60, {})
    fake.add(WINDOW_BUCKET, 3, 0, {"app": "Notion", "title": "Plan ✨ résumé"})
    fake.add(AFK_BUCKET, 0, 120, {"status": "not-afk"})
    fake.add(AFK_BUCKET, 2, 60, {"status": "afk"})
    fake.add(
        WEB_BUCKET,
        1,
        30,
        {"url": "https://www.github.com/x", "title": "GitHub", "audible": False, "tabCount": 4},
    )
    fake.add(WEB_BUCKET, 1.5, 30, {"url": "chrome://newtab/", "title": "New Tab"})
    fake.add(WEB_BUCKET, 2, 30, {"url": "https://news.ycombinator.com/", "title": "HN"})
    return fake


@pytest.fixture
def ingested(conn: sqlite3.Connection) -> sqlite3.Connection:
    poll(conn, [ActivityWatch(fixture_aw())], now=at(30))
    return conn


BIG = 200  # window events in the big store


@pytest.fixture
def big(conn: sqlite3.Connection) -> sqlite3.Connection:
    """BIG window signals plus two AFK rows: room for the ratio checks to matter."""
    fake = FakeAW({WINDOW_BUCKET: "currentwindow", AFK_BUCKET: "afkstatus"})
    for i in range(BIG):
        fake.add(WINDOW_BUCKET, i, 30, {"app": f"App {i % 7}", "title": f"t{i}"})
    fake.add(AFK_BUCKET, 0, 60, {"status": "not-afk"})
    fake.add(AFK_BUCKET, 1, 60, {"status": "afk"})
    poll(conn, [ActivityWatch(fake)], now=at(BIG + 10))
    assert len(signal_rows(conn)) == BIG
    return conn


def signal_rows(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute("SELECT * FROM signals ORDER BY observation_id")]


def observation_rows(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute("SELECT * FROM observations ORDER BY id")]


def observation_id(conn: sqlite3.Connection, source: str, title: str) -> int:
    for row in conn.execute("SELECT id, payload FROM observations WHERE source = ?", (source,)):
        if f'"title": "{title}"' in row["payload"]:
            return row["id"]
    raise AssertionError(f"no {source} observation titled {title!r}")


def corrupt_payload(conn: sqlite3.Connection, obs_id: int) -> None:
    """Test-only stand-in for a damaged row: raw rows are never edited in production."""
    conn.execute("UPDATE observations SET payload = '{not json' WHERE id = ?", (obs_id,))


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --- result identical ------------------------------------------------------------


@pytest.mark.parametrize("batch_size", [1, 2, 1000])
def test_rebuild_reproduces_ingested_signals_row_for_row(
    ingested: sqlite3.Connection, batch_size: int
) -> None:
    conn = ingested
    signals, observations = signal_rows(conn), observation_rows(conn)
    assert len(signals) == 7 and len(observations) == 9

    result = rebuild_signals(conn, AW, batch_size=batch_size)

    assert signal_rows(conn) == signals
    assert observation_rows(conn) == observations  # raw layer untouched
    assert result.signals_before == result.signals_after == 7
    assert result.skipped == 0 and result.failed_ids == ()
    assert conn.execute(
        "SELECT COUNT(*) FROM signals WHERE source = ?", (AFK_SOURCE,)
    ).fetchone()[0] == 0
    assert not conn.in_transaction


def test_rebuild_repairs_stale_and_missing_signals(ingested: sqlite3.Connection) -> None:
    conn = ingested
    expected = signal_rows(conn)
    with transaction(conn):
        conn.execute("UPDATE signals SET title = 'stale', domain = NULL")
        conn.execute("DELETE FROM signals WHERE observation_id = ?", (expected[0][0],))
        afk_id = conn.execute(
            "SELECT id FROM observations WHERE source = ? LIMIT 1", (AFK_SOURCE,)
        ).fetchone()[0]
        conn.execute(  # a signal AFK should never have
            "INSERT INTO signals (observation_id, source, started_at, ended_at) "
            "SELECT id, source, started_at, ended_at FROM observations WHERE id = ?",
            (afk_id,),
        )
    rebuild_signals(conn, AW)
    assert signal_rows(conn) == expected


def test_rebuild_of_an_empty_store(conn: sqlite3.Connection) -> None:
    result = rebuild_signals(conn, AW)
    assert (result.signals_before, result.signals_after, result.skipped) == (0, 0, 0)


def test_rebuild_refuses_to_run_inside_a_transaction(ingested: sqlite3.Connection) -> None:
    conn = ingested
    before = signal_rows(conn)
    with transaction(conn):
        with pytest.raises(RuntimeError, match="own transaction"):
            rebuild_signals(conn, AW)
    assert signal_rows(conn) == before


def test_rebuild_rejects_a_nonpositive_batch_size(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        rebuild_signals(conn, AW, batch_size=0)


# --- atomicity -------------------------------------------------------------------


def test_database_failure_mid_rebuild_rolls_back_everything(
    ingested: sqlite3.Connection,
) -> None:
    conn = ingested
    signals, observations = signal_rows(conn), observation_rows(conn)
    last = signals[-1][0]
    # Fail the insert of the last signal, after the wipe and earlier batches ran.
    conn.execute(
        "CREATE TEMP TRIGGER fail_last BEFORE INSERT ON signals "
        f"WHEN NEW.observation_id = {last} BEGIN SELECT RAISE(ABORT, 'injected'); END"
    )
    with pytest.raises(sqlite3.DatabaseError, match="injected"):
        rebuild_signals(conn, AW, batch_size=1)
    conn.execute("DROP TRIGGER fail_last")

    assert not conn.in_transaction
    assert signal_rows(conn) == signals
    assert observation_rows(conn) == observations


def test_interrupt_mid_rebuild_rolls_back_everything(ingested: sqlite3.Connection) -> None:
    conn = ingested
    signals = signal_rows(conn)
    calls = 0

    def interrupted(source: str, payload: str):
        nonlocal calls
        calls += 1
        if calls == 6:
            raise KeyboardInterrupt  # not a malformed payload: never skipped
        return AW(source, payload)

    with pytest.raises(KeyboardInterrupt):
        rebuild_signals(conn, interrupted, batch_size=1)
    assert not conn.in_transaction
    assert signal_rows(conn) == signals


def test_rolled_back_rebuild_is_invisible_to_other_connections(
    ingested: sqlite3.Connection, db_path: Path
) -> None:
    conn = ingested
    signals = signal_rows(conn)
    other = connect(db_path)
    seen: list[int] = []

    def peeking(source: str, payload: str):
        # Mid-rebuild, after the wipe: another reader still sees every old signal.
        seen.append(other.execute("SELECT COUNT(*) FROM signals").fetchone()[0])
        raise KeyboardInterrupt

    try:
        with pytest.raises(KeyboardInterrupt):
            rebuild_signals(conn, peeking)
        assert seen == [len(signals)]
        assert signal_rows(other) == signals
    finally:
        other.close()


# --- malformed payloads ----------------------------------------------------------


def test_malformed_payload_is_skipped_counted_and_logged(
    ingested: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    conn = ingested
    expected = signal_rows(conn)
    bad = observation_id(conn, WINDOW_SOURCE, "GitHub")
    corrupt_payload(conn, bad)

    with caplog.at_level(logging.WARNING):
        result = rebuild_signals(conn, AW)

    assert result.skipped == 1 and result.failed_ids == (bad,)
    assert result.signals_after == len(expected) - 1
    assert signal_rows(conn) == [row for row in expected if row[0] != bad]
    assert any(f"observation {bad} " in r.getMessage() for r in caplog.records)


def test_malformed_afk_payload_is_not_a_failure(ingested: sqlite3.Connection) -> None:
    conn = ingested
    expected = signal_rows(conn)
    afk_id = conn.execute(
        "SELECT id FROM observations WHERE source = ? ORDER BY id LIMIT 1", (AFK_SOURCE,)
    ).fetchone()[0]
    corrupt_payload(conn, afk_id)  # AFK has no content to project, so it is never parsed
    result = rebuild_signals(conn, AW)
    assert result.skipped == 0
    assert signal_rows(conn) == expected


def test_only_the_first_failures_are_logged_individually(
    ingested: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = ingested
    monkeypatch.setattr(signals_module, "MAX_LOGGED_FAILURES", 1)
    bad = [observation_id(conn, WEB_SOURCE, t) for t in ("GitHub", "New Tab", "HN")]
    for obs_id in bad:
        corrupt_payload(conn, obs_id)
    with caplog.at_level(logging.WARNING):
        result = rebuild_signals(conn, AW)
    assert result.skipped == 3  # 3 of 7 content observations: under half
    assert result.failed_ids == (min(bad),)
    messages = [r.getMessage() for r in caplog.records]
    assert sum("skipping observation" in m for m in messages) == 1
    assert any("2 more observations skipped" in m for m in messages)


def test_more_than_half_failing_aborts_and_rolls_back(ingested: sqlite3.Connection) -> None:
    conn = ingested
    signals = signal_rows(conn)
    ids = [row[0] for row in signals]
    for obs_id in ids[:4]:  # 4 of 7 content observations
        corrupt_payload(conn, obs_id)

    with pytest.raises(RebuildAborted) as exc:
        rebuild_signals(conn, AW)

    assert exc.value.failed == 4
    assert exc.value.failed_ids == tuple(ids[:4])
    assert "rolled back" in str(exc.value)
    assert not conn.in_transaction
    assert signal_rows(conn) == signals


def test_a_projector_bug_failing_every_row_aborts(ingested: sqlite3.Connection) -> None:
    conn = ingested
    signals = signal_rows(conn)

    def broken(source: str, payload: str):
        if source == AFK_SOURCE:
            return None
        raise TypeError("bug")

    with pytest.raises(RebuildAborted):
        rebuild_signals(conn, broken)
    assert signal_rows(conn) == signals


def test_a_projector_failing_every_row_aborts_early(big: sqlite3.Connection) -> None:
    conn = big
    signals = signal_rows(conn)
    attempts = 0

    def broken(source: str, payload: str):
        nonlocal attempts
        attempts += 1
        raise TypeError("bug")

    with pytest.raises(RebuildAborted) as exc:
        rebuild_signals(conn, broken)
    # Stops once failures exceed half of everything that could still be content,
    # i.e. after about half the table rather than after scanning all of it.
    assert attempts == exc.value.failed
    assert attempts <= (BIG + 2) // 2 + 1
    assert len(exc.value.failed_ids) == signals_module.MAX_LOGGED_FAILURES
    assert not exc.value.shrink
    assert signal_rows(conn) == signals


def test_a_projector_wrongly_returning_none_aborts_as_a_shrink(big: sqlite3.Connection) -> None:
    conn = big
    signals = signal_rows(conn)

    def drops_everything(source: str, payload: str):
        return None  # raises nothing, so nothing counts as failed

    with pytest.raises(RebuildAborted, match=rf"shrink from {BIG} to 0 rows") as exc:
        rebuild_signals(conn, drops_everything)
    assert exc.value.shrink and exc.value.failed == 0
    assert signal_rows(conn) == signals


def test_shrinking_to_half_is_allowed(big: sqlite3.Connection) -> None:
    conn = big

    def drops_odd_titles(source: str, payload: str):
        signal = AW(source, payload)
        if signal is not None and int(signal.title[1:]) % 2:
            return None
        return signal

    result = rebuild_signals(conn, drops_odd_titles)
    assert (result.signals_before, result.signals_after) == (BIG, BIG // 2)


def test_allow_shrink_overrides_the_shrink_check(big: sqlite3.Connection) -> None:
    conn = big
    result = rebuild_signals(
        conn, lambda source, payload: None, allow_shrink=True
    )
    assert (result.signals_before, result.signals_after) == (BIG, 0)


def test_small_stores_may_shrink(ingested: sqlite3.Connection) -> None:
    conn = ingested  # 7 signals: below SHRINK_CHECK_MIN_SIGNALS
    result = rebuild_signals(conn, lambda source, payload: None)
    assert (result.signals_before, result.signals_after) == (7, 0)


# --- CLI ---------------------------------------------------------------------------


def test_cli_rebuild_signals_reports_counts(
    capsys: pytest.CaptureFixture[str], db_path: Path
) -> None:
    conn = connect(db_path)
    try:
        poll(conn, [ActivityWatch(fixture_aw())], now=at(30))
        expected = signal_rows(conn)
    finally:
        conn.close()

    code, out, err = run(capsys, "rebuild-signals", "--db-path", str(db_path))

    assert code == 0, err
    assert str(db_path) in out
    assert re.search(r"signals before\s+7\n", out)
    assert re.search(r"signals after\s+7\n", out)
    assert re.search(r"skipped\s+0\s", out)
    assert "warning" not in out
    conn = connect(db_path)
    try:
        assert signal_rows(conn) == expected
    finally:
        conn.close()


def test_cli_rebuild_signals_reports_skipped_rows(
    capsys: pytest.CaptureFixture[str], db_path: Path
) -> None:
    conn = connect(db_path)
    try:
        poll(conn, [ActivityWatch(fixture_aw())], now=at(30))
        bad = observation_id(conn, WEB_SOURCE, "HN")
        corrupt_payload(conn, bad)
    finally:
        conn.close()

    code, out, _ = run(capsys, "--db-path", str(db_path), "rebuild-signals")

    assert code == 0
    assert re.search(r"signals after\s+6\n", out)
    assert re.search(r"skipped\s+1\s", out)
    assert f"first ids: {bad}" in out


def test_cli_rebuild_signals_abort_exits_nonzero(
    capsys: pytest.CaptureFixture[str], db_path: Path
) -> None:
    conn = connect(db_path)
    try:
        poll(conn, [ActivityWatch(fixture_aw())], now=at(30))
        ids = [row[0] for row in signal_rows(conn)]
        for obs_id in ids:
            corrupt_payload(conn, obs_id)
    finally:
        conn.close()

    code, out, err = run(capsys, "--db-path", str(db_path), "rebuild-signals")

    assert code == 1
    assert out == ""
    assert "aborted" in err and "signals unchanged" in err
    conn = connect(db_path)
    try:
        assert len(signal_rows(conn)) == len(ids)
    finally:
        conn.close()


def test_cli_rebuild_signals_on_a_fresh_db(
    capsys: pytest.CaptureFixture[str], db_path: Path
) -> None:
    connect(db_path).close()  # created and migrated, nothing ingested yet
    code, out, _ = run(capsys, "--db-path", str(db_path), "rebuild-signals")
    assert code == 0
    assert re.search(r"signals after\s+0\n", out)


def test_cli_rebuild_signals_refuses_a_missing_db(
    capsys: pytest.CaptureFixture[str], db_path: Path
) -> None:
    code, out, err = run(capsys, "--db-path", str(db_path), "rebuild-signals")
    assert code == 1
    assert out == ""
    assert f"no database at {db_path}" in err and "ingest" in err
    assert not db_path.exists()  # never created


def test_cli_rebuild_signals_says_how_many_ids_it_left_out(
    capsys: pytest.CaptureFixture[str], db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(signals_module, "MAX_LOGGED_FAILURES", 1)
    conn = connect(db_path)
    try:
        poll(conn, [ActivityWatch(fixture_aw())], now=at(30))
        bad = sorted(observation_id(conn, WEB_SOURCE, t) for t in ("GitHub", "HN"))
        for obs_id in bad:
            corrupt_payload(conn, obs_id)
    finally:
        conn.close()

    code, out, _ = run(capsys, "--db-path", str(db_path), "rebuild-signals")

    assert code == 0
    assert f"first ids: {bad[0]} (and 1 more)" in out


def test_cli_rebuild_signals_allow_shrink(
    capsys: pytest.CaptureFixture[str], db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(signals_module, "SHRINK_CHECK_MIN_SIGNALS", 1)
    fake = FakeAW({AFK_BUCKET: "afkstatus"})
    fake.add(AFK_BUCKET, 0, 60, {"status": "not-afk"})
    fake.add(AFK_BUCKET, 1, 60, {"status": "afk"})
    conn = connect(db_path)
    try:
        poll(conn, [ActivityWatch(fake)], now=at(30))
        with transaction(conn):  # signals an older mapping gave, which the current one drops
            conn.execute(
                "INSERT INTO signals (observation_id, source, started_at, ended_at) "
                "SELECT id, source, started_at, ended_at FROM observations"
            )
    finally:
        conn.close()

    code, _, err = run(capsys, "--db-path", str(db_path), "rebuild-signals")
    assert code == 1
    assert "shrink from 2 to 0 rows" in err and "first failing" not in err
    assert "--allow-shrink" in err

    code, out, _ = run(capsys, "--db-path", str(db_path), "rebuild-signals", "--allow-shrink")
    assert code == 0
    assert re.search(r"signals after\s+0\n", out)
