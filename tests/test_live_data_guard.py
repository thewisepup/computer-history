from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from live_data_guard import GUARDED_ENV_VARS, LIVE_DATA_DIR, LiveDataTouched

from computer_history.sources.capture_spool.paths import SPOOL_ENV_VAR
from computer_history.store import DB_ENV_VAR, Profile, connect, default_db_path, resolve_db_path

PROBE = LIVE_DATA_DIR / "test-guard-probe-that-never-exists.db"


def test_home_is_a_sandbox_and_defaults_land_in_it() -> None:
    assert Path.home() != LIVE_DATA_DIR.parents[2]
    assert not default_db_path(Profile.STABLE).is_relative_to(LIVE_DATA_DIR)
    assert not any(os.environ.get(name) for name in GUARDED_ENV_VARS)


def test_the_guard_watches_the_folder_and_variables_the_app_really_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(LIVE_DATA_DIR.parents[2]))
    assert default_db_path(Profile.STABLE) == LIVE_DATA_DIR / "history.db"
    assert set(GUARDED_ENV_VARS) == {DB_ENV_VAR, SPOOL_ENV_VAR}


@pytest.mark.parametrize(
    "touch",
    [
        lambda: open(PROBE, "rb"),
        lambda: open(str(PROBE).replace("ComputerHistory", "computerhistory"), "rb"),
        lambda: open(str(PROBE).replace("Library", "LIBRARY"), "rb"),
        lambda: sqlite3.connect(f"file:{PROBE}?mode=ro", uri=True),
        lambda: sqlite3.connect(f"file://localhost{PROBE}?mode=ro", uri=True),
        lambda: sqlite3.connect(f"file:{quote(str(PROBE))}?mode=ro", uri=True),
        lambda: sqlite3.connect(f"file:{LIVE_DATA_DIR}/./{PROBE.name}?mode=ro", uri=True),
        lambda: connect(PROBE, create=False),
        lambda: os.remove(PROBE),
        lambda: os.rename(PROBE, PROBE.with_suffix(".moved")),
    ],
    ids=[
        "open",
        "open-lowercased",
        "open-uppercased",
        "sqlite-uri",
        "sqlite-localhost-uri",
        "sqlite-percent-encoded",
        "sqlite-unnormalized",
        "store-connect",
        "remove",
        "rename",
    ],
)
def test_touching_live_data_raises(touch) -> None:
    with pytest.raises(LiveDataTouched):
        touch()
    assert not PROBE.exists()


def test_the_real_folder_stays_guarded_when_home_was_redirected_first(tmp_path: Path) -> None:
    script = f"import live_data_guard\nopen({str(PROBE)!r}, 'rb')\n"
    env = {**os.environ, "HOME": str(tmp_path)}
    run = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "LiveDataTouched" in run.stderr
    assert not PROBE.exists()


def test_a_run_given_no_database_path_lands_in_the_sandbox_not_the_live_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    connect(resolve_db_path(None, Profile.STABLE)).close()
    assert default_db_path(Profile.STABLE).exists()
    assert default_db_path(Profile.STABLE).is_relative_to(tmp_path)
