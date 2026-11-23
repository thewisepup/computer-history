from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "guard-live-data.py"
LIVE = "~/Library/Application Support/ComputerHistory"


def _load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("guard_live_data", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_hook()


def _run(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, check=False
    )


def _bash(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/tmp"})


BARE_CLI = [
    "computer-history ingest",
    "  computer-history status",
    "cd /tmp && computer-history restore --from x.db",
    "true; computer-history ingest",
    "false || computer-history ingest",
    "echo hi | computer-history ingest",
    "echo $(computer-history status)",
    'echo "$(computer-history status)"',
    "echo `computer-history status`",
    "FOO=1 computer-history ingest",
    "env FOO=1 computer-history ingest",
    "env -i PATH=/usr/bin computer-history ingest",
    "sudo -u brandon computer-history ingest",
    "time computer-history ingest",
    "exec computer-history ingest",
    "nohup computer-history ingest --watch &",
    "timeout 10 computer-history ingest",
    "xargs -n1 computer-history restore --from",
    "(computer-history ingest)",
    "{ computer-history ingest; }",
    "if true; then computer-history ingest; fi",
    "diff <(computer-history status) /dev/null",
    '"computer-history" ingest',
    "\\computer-history ingest",
    ">/dev/null computer-history ingest",
    "bash -c 'computer-history ingest'",
    'zsh -lc "cd /tmp && computer-history ingest"',
    "eval computer-history ingest",
    "ls\ncomputer-history ingest",
    "~/.local/bin/computer-history ingest",
    "$HOME/.local/bin/computer-history ingest",
]

ALLOWED = [
    ".venv/bin/computer-history ingest",
    "./.venv/bin/computer-history status",
    "/Users/me/workspace/computer-history/.venv/bin/computer-history status",
    '"$(dirname "$(scripts/venv-python)")/computer-history" status',
    'git commit -m "Block bare computer-history in the guard"',
    "git commit -m 'computer-history ingest is blocked'",
    "grep -rn computer-history computer_history/cli/README.md",
    "rg 'computer-history ingest' docs",
    "gh pr create --title 'computer-history: guard' --body x",
    "echo computer-history",
    "which computer-history",
    "type computer-history",
    "command -v computer-history",
    "ls ~/workspace/computer-history",
    "cd ../computer-history && git status",
    "echo '$(computer-history status)'",
    "echo \\`computer-history status\\`",
    "# computer-history ingest",
    "echo 'unterminated computer-history",
    "git commit -F - <<'EOF'\ncomputer-history ingest no longer runs\nEOF",
    "git commit -m \"$(cat <<'EOF'\nSubject\n\ncomputer-history ingest\nEOF\n)\"",
    "cat <<-EOF\n\tcomputer-history ingest\n\tEOF\necho done",
    "bash scripts/check.sh computer-history",
    "",
]


@pytest.mark.parametrize("command", BARE_CLI)
def test_running_the_cli_from_path_is_blocked(command: str) -> None:
    assert guard.runs_cli_from_path(command)


@pytest.mark.parametrize("command", ALLOWED)
def test_path_qualified_runs_and_mentions_are_allowed(command: str) -> None:
    assert not guard.runs_cli_from_path(command)


def test_a_command_after_a_heredoc_is_still_checked() -> None:
    assert guard.runs_cli_from_path("cat <<EOF\nhello\nEOF\ncomputer-history ingest")


@pytest.mark.parametrize(
    "command",
    [
        f"ls {LIVE}",
        f"ls {LIVE}>/dev/null",
        f"ls {LIVE}</dev/null",
        f"cp {LIVE},backup /tmp",
        f'sqlite3 "{LIVE}/history.db"',
    ],
)
def test_naming_the_live_folder_is_blocked(command: str) -> None:
    assert guard.names_live_folder(command)


def test_the_dev_folder_is_not_the_live_folder() -> None:
    assert not guard.names_live_folder(f"ls {LIVE}-dev/")


def test_hook_blocks_a_bare_cli_call_with_exit_2() -> None:
    result = _run(_bash("cd /tmp && computer-history ingest"))
    assert result.returncode == 2
    assert ".venv/bin/computer-history" in result.stderr


def test_hook_allows_the_dev_cli() -> None:
    result = _run(_bash(".venv/bin/computer-history status"))
    assert (result.returncode, result.stderr) == (0, "")


def test_hook_blocks_a_write_into_the_live_folder() -> None:
    event = {"tool_name": "Write", "tool_input": {"file_path": f"{LIVE}/x.txt"}, "cwd": "/tmp"}
    result = _run(json.dumps(event))
    assert result.returncode == 2
    assert "live data folder" in result.stderr


@pytest.mark.parametrize(
    "stdin",
    ["not json", "[]", json.dumps({"tool_name": "Write", "tool_input": ["x"]})],
)
def test_hook_blocks_input_it_cannot_check(stdin: str) -> None:
    result = _run(stdin)
    assert result.returncode == 2
    assert "could not check this call" in result.stderr


def test_hook_parses_as_python_3_9() -> None:
    ast.parse(HOOK.read_text(encoding="utf-8"), feature_version=(3, 9))
