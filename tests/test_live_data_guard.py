from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from live_data_guard import GUARDED_ENV_VARS, LIVE_DATA_DIR, LiveDataTouched

from computer_history.store import connect, default_db_path
from computer_history.store import db as store_db
from computer_history.store.paths import resolve_db_path

PROBE = LIVE_DATA_DIR / "test-guard-probe-that-never-exists.db"


def test_home_is_a_sandbox_and_defaults_land_in_it() -> None:
    assert Path.home() != LIVE_DATA_DIR.parents[2]
    assert not default_db_path().is_relative_to(LIVE_DATA_DIR)
    assert not any(os.environ.get(name) for name in GUARDED_ENV_VARS)


def test_the_guard_watches_the_folder_the_app_really_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(LIVE_DATA_DIR.parents[2]))
    assert default_db_path() == LIVE_DATA_DIR / "history.db"


# Each probe cannot create its missing file, so a broken guard fails here and writes nothing.
@pytest.mark.parametrize(
    "touch",
    [
        lambda: open(PROBE, "rb"),
        lambda: sqlite3.connect(f"file:{PROBE}?mode=ro", uri=True),
        lambda: sqlite3.connect(f"file:{LIVE_DATA_DIR}/./{PROBE.name}?mode=ro", uri=True),
        lambda: connect(PROBE, create=False),
        lambda: os.remove(PROBE),
        lambda: os.rename(PROBE, PROBE.with_suffix(".moved")),
    ],
    ids=["open", "sqlite-uri", "sqlite-unnormalized", "store-connect", "remove", "rename"],
)
def test_touching_live_data_raises(touch) -> None:
    with pytest.raises(LiveDataTouched):
        touch()
    assert not PROBE.exists()


def test_a_path_dropping_bug_lands_in_the_sandbox_not_the_live_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The 2026-11-19 incident: a mutant made connect() drop its path and use the default."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(store_db, "resolve_db_path", lambda explicit=None: resolve_db_path(None))
    connect(tmp_path / "meant-for-this.db").close()
    fallback = tmp_path / "Library" / "Application Support" / "ComputerHistory" / "history.db"
    assert fallback.exists()
    assert not (tmp_path / "meant-for-this.db").exists()
