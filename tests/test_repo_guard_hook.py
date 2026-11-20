"""The checked-in Claude Code hook that keeps coding agents off the live data folder."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
BLOCKED = 2


@dataclass(frozen=True)
class Verdict:
    code: int
    reason: str


def guard_command(tool_name: str) -> str | None:
    settings = json.loads((REPO / ".claude" / "settings.json").read_text())
    for entry in settings["hooks"]["PreToolUse"]:
        if re.fullmatch(entry["matcher"], tool_name):
            return entry["hooks"][0]["command"]
    return None


def run_hook(
    tool_name: str, tool_input: dict[str, Any], cwd: Path = REPO, home: Path | None = None
) -> Verdict:
    command = guard_command(tool_name)
    assert command is not None, f"no PreToolUse hook matches {tool_name}"
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": str(cwd),
    }
    done = subprocess.run(
        command,
        shell=True,
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(REPO),
            "HOME": str(home or os.environ["HOME"]),
        },
        cwd=REPO,
        timeout=10,
    )
    return Verdict(done.returncode, done.stderr)


def test_bash_naming_the_live_folder_is_blocked_with_a_reason():
    verdict = run_hook(
        "Bash", {"command": "sqlite3 ~/Library/Application\\ Support/ComputerHistory/history.db"}
    )

    assert verdict.code == BLOCKED
    assert "live data folder" in verdict.reason
    assert "ComputerHistory-dev" in verdict.reason


@pytest.mark.parametrize(
    "command",
    [
        'ls "$HOME/Library/Application Support/ComputerHistory/"',
        "rm -rf ${HOME}/Library/Application\\ Support/ComputerHistory",
        "cat '/Users/brandon/Library/Application Support/ComputerHistory/spool/a.jsonl'",
        "cp x ~/library/APPLICATION SUPPORT/computerhistory/history.db",
        'cd ~/Library/"Application Support"/ComputerHistory && ls',
        "du -sh ~/Library/Application\\ Support/ComputerHistory/*",
    ],
)
def test_every_spelling_of_the_live_folder_is_blocked(command: str):
    assert run_hook("Bash", {"command": command}).code == BLOCKED


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [
        (
            "Edit",
            {
                "file_path": "/Users/brandon/Library/Application Support/ComputerHistory/x.json",
                "old_string": "a",
                "new_string": "b",
            },
        ),
        ("Write", {"file_path": "~/Library/Application Support/ComputerHistory/x", "content": ""}),
        (
            "NotebookEdit",
            {
                "notebook_path": "$HOME/Library/Application Support/computerhistory/n.ipynb",
                "new_source": "",
            },
        ),
    ],
)
def test_file_tools_aimed_at_the_live_folder_are_blocked(
    tool_name: str, tool_input: dict[str, Any]
):
    assert run_hook(tool_name, tool_input).code == BLOCKED


def test_a_relative_path_resolved_into_the_live_folder_is_blocked(tmp_path: Path):
    support = tmp_path / "Library" / "Application Support"
    (support / "ComputerHistory").mkdir(parents=True)

    verdict = run_hook("Write", {"file_path": "ComputerHistory/x", "content": ""}, cwd=support)

    assert verdict.code == BLOCKED


def test_a_symlink_into_the_live_folder_is_blocked(tmp_path: Path):
    live = tmp_path / "Library" / "Application Support" / "ComputerHistory"
    live.mkdir(parents=True)
    (tmp_path / "shortcut").symlink_to(live)

    verdict = run_hook("Edit", {"file_path": str(tmp_path / "shortcut" / "history.db")})

    assert verdict.code == BLOCKED


@pytest.mark.parametrize("path", ["~/shortcut/history.db", "$HOME/shortcut/history.db"])
def test_a_symlink_reached_through_home_is_blocked(tmp_path: Path, path: str):
    live = tmp_path / "Library" / "Application Support" / "ComputerHistory"
    live.mkdir(parents=True)
    (tmp_path / "shortcut").symlink_to(live)

    assert run_hook("Write", {"file_path": path, "content": ""}, home=tmp_path).code == BLOCKED


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [
        ("Bash", {"command": "ls ~/Library/Application\\ Support/ComputerHistory-dev/"}),
        ("Bash", {"command": 'rm "$HOME/Library/Application Support/ComputerHistory-dev"'}),
        ("Bash", {"command": "ls ~/Library/Application\\ Support/"}),
        ("Bash", {"command": ".venv/bin/python -m pytest -q"}),
        (
            "Write",
            {"file_path": "~/Library/Application Support/ComputerHistory-dev/x", "content": ""},
        ),
        (
            "Edit",
            {
                "file_path": "computer_history/store/paths.py",
                "old_string": "a",
                "new_string": '"~/Library/Application Support/ComputerHistory/history.db"',
            },
        ),
    ],
)
def test_the_dev_folder_unrelated_paths_and_file_contents_pass(
    tool_name: str, tool_input: dict[str, Any]
):
    assert run_hook(tool_name, tool_input) == Verdict(0, "")


@pytest.mark.parametrize("tool_name", ["Read", "Grep", "Glob"])
def test_only_bash_and_the_file_editing_tools_are_guarded(tool_name: str):
    assert guard_command(tool_name) is None
