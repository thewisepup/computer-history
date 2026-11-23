#!/usr/bin/env python3
"""PreToolUse guard: blocks calls that name the live data folder or run the stable CLI from PATH.

Read, Grep and Glob are not guarded: reading live data is allowed, writing and running are not.
"""

import json
import os
import re
import sys

LIVE_FOLDER_PATH = "~/Library/Application Support/ComputerHistory"
LIVE_FOLDER = re.compile(
    re.escape(LIVE_FOLDER_PATH[len("~/") :]) + r"(?=$|[/\s*;&|)<>,])", re.IGNORECASE
)
PATH_FIELDS = ("file_path", "notebook_path")
CLI = "computer-history"
DEV_CLI = ".venv/bin/" + CLI
STABLE_LINK = ".local/bin/" + CLI
LIVE_FOLDER_MESSAGE = (
    "Blocked by .claude/hooks/guard-live-data.py: this call names Brandon's live data folder "
    f"({LIVE_FOLDER_PATH}/), which holds his real database, spool and screenshots. Use the "
    f"dev folder ({LIVE_FOLDER_PATH}-dev/) or a temp folder with --db-path and --spool-path "
    "instead. If Brandon asked for this call on live data, tell him it is blocked and let him "
    "run it himself."
)
BARE_CLI_MESSAGE = (
    f"Blocked by .claude/hooks/guard-live-data.py: a bare `{CLI}` resolves through PATH to "
    f"~/{STABLE_LINK}, the stable install, which runs on Brandon's live data folder. Run the "
    f"checkout's dev CLI instead: {DEV_CLI} (in a fresh worktree, run scripts/venv-python "
    "once to create .venv). If Brandon asked for this call on the stable install, tell him it "
    "is blocked and let him run it himself."
)
UNCHECKED_MESSAGE = (
    "Blocked by .claude/hooks/guard-live-data.py: it could not check this call ({error}). "
    "Tell Brandon the guard needs fixing."
)


def names_live_folder(text):
    """Says whether text names the live data folder, ignoring quotes and repeated slashes."""
    flattened = re.sub(r"/+", "/", re.sub(r"[\"']|\\(?=\s)", "", text))
    return bool(LIVE_FOLDER.search(flattened))


def runs_cli_from_path(command):
    """Says whether a Bash command runs the CLI by its bare name or through the stable link."""
    from shell_commands import command_words

    return any(w == CLI or w.endswith("/" + STABLE_LINK) for w in command_words(command))


def blocked_reason(tool_name, tool_input, cwd):
    """Returns the message to block a tool call with, or None to let it run."""
    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return None
        if names_live_folder(command):
            return LIVE_FOLDER_MESSAGE
        return BARE_CLI_MESSAGE if runs_cli_from_path(command) else None
    for field in PATH_FIELDS:
        path = tool_input.get(field)
        if not isinstance(path, str) or not path:
            continue
        expanded = os.path.join(cwd or os.getcwd(), os.path.expanduser(os.path.expandvars(path)))
        for candidate in (path, expanded, os.path.realpath(expanded)):
            if names_live_folder(candidate):
                return LIVE_FOLDER_MESSAGE
    return None


def main():
    try:
        event = json.load(sys.stdin)
        reason = blocked_reason(
            event.get("tool_name", ""), event.get("tool_input") or {}, event.get("cwd")
        )
    except Exception as error:
        reason = UNCHECKED_MESSAGE.format(error=f"{type(error).__name__}: {error}")
    if reason is None:
        return
    print(reason, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
