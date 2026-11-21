"""A temp home with its own live and dev folders, a checkout to run code from, and a CLI runner."""

from __future__ import annotations

from pathlib import Path

import pytest
from cli_output import RunCli

from computer_history import cli
from computer_history.host import Host
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


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str]) -> RunCli:
    """Run the CLI with its code at the given location (and a host adapter, if given)."""

    def run_cli(code: Path, *argv: str, host: Host | None = None) -> tuple[int, list[str], str]:
        exit_code = cli.main(list(argv), code=code, host=host)
        captured = capsys.readouterr()
        return exit_code, captured.out.splitlines(), captured.err

    return run_cli
