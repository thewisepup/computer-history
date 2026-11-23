#!/usr/bin/env python3
"""PreToolUse guard: blocks calls that name the live data folder or run the stable CLI from PATH.

Read, Grep and Glob are not guarded: reading live data is allowed, writing and running are not.
"""

import json
import os
import re
import sys

LIVE_FOLDER = re.compile(
    r"library/application support/computerhistory(?=$|[/\s*;&|)<>,])", re.IGNORECASE
)
PATH_FIELDS = ("file_path", "notebook_path")
CLI = "computer-history"
STABLE_LINK = ".local/bin/" + CLI
REDIRECT = "\0redirect"
SUBSTITUTION = "\0substitution"
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
HEREDOC = re.compile(r"-?[ \t]*(?:'([^']*)'|\"([^\"]*)\"|\\?([^\s;&|<>()]+))")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "fish")
WRAPPERS = {
    "env": ("-u", "-C", "-P", "-S"),
    "sudo": ("-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T"),
    "time": (),
    "exec": ("-a",),
    "command": (),
    "builtin": (),
    "nohup": (),
    "nice": ("-n",),
    "caffeinate": ("-t", "-w"),
    "xargs": ("-I", "-J", "-L", "-n", "-P", "-s", "-E", "-d", "-R", "-S"),
    "timeout": ("-s", "-k"),
    "then": (),
    "do": (),
    "else": (),
    "elif": (),
    "if": (),
    "while": (),
    "until": (),
    "!": (),
    "{": (),
}
POSITIONAL_BEFORE_COMMAND = {"timeout": 1}
LIVE_FOLDER_MESSAGE = (
    "Blocked by .claude/hooks/guard-live-data.py: this call names Brandon's live data folder "
    "(~/Library/Application Support/ComputerHistory/), which holds his real database, spool "
    "and screenshots. Use the dev folder (~/Library/Application Support/ComputerHistory-dev/) "
    "or a temp folder with --db-path and --spool-path instead. If Brandon asked for this "
    "call on live data, tell him it is blocked and let him run it himself."
)
BARE_CLI_MESSAGE = (
    "Blocked by .claude/hooks/guard-live-data.py: a bare `computer-history` resolves through "
    "PATH to ~/.local/bin/computer-history, the stable install, which runs on Brandon's live "
    "data folder. Run the checkout's dev CLI instead: .venv/bin/computer-history (in a fresh "
    "worktree, run scripts/venv-python once to create .venv). If Brandon asked for this call "
    "on the stable install, tell him it is blocked and let him run it himself."
)


def names_live_folder(text):
    flattened = re.sub(r"/+", "/", re.sub(r"[\"']|\\(?=\s)", "", text))
    return bool(LIVE_FOLDER.search(flattened))


class _Frame:
    def __init__(self, closer):
        self.closer = closer
        self.quote = None
        self.depth = 0
        self.word = None
        self.words = []
        self.heredocs = []

    def end_word(self):
        if self.word is not None:
            self.words.append("".join(self.word))
            self.word = None

    def end_command(self, done):
        self.end_word()
        if self.words:
            done.append(self.words)
        self.words = []

    def add(self, text):
        if self.word is None:
            self.word = []
        self.word.append(text)


def _skip_heredocs(text, i, frame):
    for delimiter, strip_tabs in frame.heredocs:
        while i < len(text):
            end = text.find("\n", i + 1)
            end = len(text) if end == -1 else end
            line = text[i + 1 : end]
            i = end
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                break
    frame.heredocs = []
    return i


def simple_commands(text):
    """Splits a shell command line into the word lists of every simple command it runs."""
    done = []
    frames = [_Frame(None)]
    i = 0
    while i < len(text):
        frame = frames[-1]
        c = text[i]
        ahead = text[i + 1] if i + 1 < len(text) else ""
        if frame.quote == "'":
            if c == "'":
                frame.quote = None
            else:
                frame.add(c)
        elif frame.quote == '"' and c == "\\" and ahead in '"\\$`':
            frame.add(ahead)
            i += 1
        elif frame.quote == '"' and c == '"':
            frame.quote = None
        elif (c == "$" and ahead == "(") or (c == "`" and frame.closer != "`"):
            frame.add(SUBSTITUTION)
            frames.append(_Frame(")" if c == "$" else "`"))
            i += 1 if c == "$" else 0
        elif frame.quote == '"':
            frame.add(c)
        elif c == "\\":
            if ahead != "\n":
                frame.add(ahead)
            i += 1
        elif c in "'\"":
            frame.quote = c
            frame.add("")
        elif (c == "`" and frame.closer == "`") or (
            c == ")" and frame.closer == ")" and frame.depth == 0
        ):
            frame.end_command(done)
            frames.pop()
        elif c == "#" and frame.word is None:
            end = text.find("\n", i)
            i = (len(text) if end == -1 else end) - 1
        elif c in " \t":
            frame.end_word()
        elif c == "\n":
            frame.end_command(done)
            i = _skip_heredocs(text, i, frame) if frame.heredocs else i
        elif c in ";&|()":
            frame.depth += {"(": 1, ")": -1}.get(c, 0) if frame.closer == ")" else 0
            frame.depth = max(frame.depth, 0)
            frame.end_command(done)
        elif c in "<>":
            frame.end_word()
            frame.words.append(REDIRECT)
            if text.startswith("<<", i) and not text.startswith("<<<", i):
                match = HEREDOC.match(text, i + 2)
                if match:
                    delimiter = next(g for g in match.groups() if g is not None)
                    frame.heredocs.append((delimiter, text[i + 2] == "-"))
                    frame.words.append(delimiter)
                    i = match.end() - 1
            else:
                while i + 1 < len(text) and text[i + 1] in "<>&|":
                    i += 1
        else:
            frame.add(c)
        i += 1
    while frames:
        frames.pop().end_command(done)
    return done


def _command_word(words):
    i = 0
    while i < len(words):
        word = words[i]
        if word == REDIRECT:
            i += 2
        elif ASSIGNMENT.match(word):
            i += 1
        elif word in WRAPPERS:
            takes_value = WRAPPERS[word]
            i += 1
            while i < len(words) and words[i].startswith("-") and words[i] != "-":
                if word == "command" and words[i] in ("-v", "-V"):
                    return None, []
                i += 2 if words[i] in takes_value else 1
            i += POSITIONAL_BEFORE_COMMAND.get(word, 0)
        else:
            return word, words[i + 1 :]
    return None, []


def _inline_scripts(word, args):
    if word == "eval":
        return [" ".join(args)]
    if os.path.basename(word) not in SHELLS:
        return []
    for k, arg in enumerate(args):
        if not arg.startswith("-"):
            return []
        if arg.startswith("--"):
            continue
        if "c" in arg[1:] and k + 1 < len(args):
            return [args[k + 1]]
    return []


def runs_cli_from_path(command):
    for words in simple_commands(command):
        word, args = _command_word(words)
        if word is None:
            continue
        if word == CLI or word.endswith("/" + STABLE_LINK):
            return True
        if any(runs_cli_from_path(script) for script in _inline_scripts(word, args)):
            return True
    return False


def blocked_reason(tool_name, tool_input, cwd):
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
        reason = (
            "Blocked by .claude/hooks/guard-live-data.py: it could not check this call "
            f"({type(error).__name__}: {error}). Tell Brandon the guard needs fixing."
        )
    if reason is None:
        return
    print(reason, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
