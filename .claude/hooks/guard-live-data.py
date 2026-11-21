#!/usr/bin/env python3
"""PreToolUse guard: blocks Bash commands and file-tool targets that name the live data folder.

Read, Grep and Glob are not guarded: reading live data is allowed, writing and running are not.
"""

import json
import os
import re
import sys

LIVE_FOLDER = re.compile(r"library/application support/computerhistory(?=$|[/\s*;&|)])", re.IGNORECASE)
PATH_FIELDS = ("file_path", "notebook_path")


def names_live_folder(text):
    flattened = re.sub(r"/+", "/", re.sub(r"[\"']|\\(?=\s)", "", text))
    return bool(LIVE_FOLDER.search(flattened))


def offending_text(tool_name, tool_input, cwd):
    if tool_name == "Bash":
        command = tool_input.get("command")
        return command if isinstance(command, str) and names_live_folder(command) else None
    for field in PATH_FIELDS:
        path = tool_input.get(field)
        if not isinstance(path, str) or not path:
            continue
        expanded = os.path.join(cwd or os.getcwd(), os.path.expanduser(os.path.expandvars(path)))
        for candidate in (path, expanded, os.path.realpath(expanded)):
            if names_live_folder(candidate):
                return path
    return None


def main():
    event = json.load(sys.stdin)
    text = offending_text(
        event.get("tool_name", ""), event.get("tool_input") or {}, event.get("cwd")
    )
    if text is None:
        return
    print(
        "Blocked by .claude/hooks/guard-live-data.py: this call names Brandon's live data folder "
        "(~/Library/Application Support/ComputerHistory/), which holds his real database, spool "
        "and screenshots. Use the dev folder (~/Library/Application Support/ComputerHistory-dev/) "
        "or a temp folder with --db-path and --spool-path instead. If Brandon asked for this "
        "call on live data, tell him it is blocked and let him run it himself.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
