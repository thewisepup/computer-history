from __future__ import annotations

from pathlib import Path

import pytest

from computer_history.store import Profile, data_folder, live_folder


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    monkeypatch.setenv("HOME", str(folder))
    return folder


@pytest.fixture
def live(home: Path) -> Path:
    folder = live_folder()
    folder.mkdir(parents=True)
    return folder


@pytest.fixture
def dev(home: Path) -> Path:
    return data_folder(Profile.DEV)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    code = tmp_path / "checkout" / "computer_history"
    code.mkdir(parents=True)
    return code
