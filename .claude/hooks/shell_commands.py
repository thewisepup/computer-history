"""Finds the programs a Bash command line runs, without running it.

Standard library and Python 3.9 only: hooks run under the system python3.
"""

import os
import re

REDIRECT = "\0redirect"
SUBSTITUTION = re.compile(r"\0\((.*)\0\)")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
HEREDOC = re.compile(r"-?[ \t]*(?:'([^']*)'|\"([^\"]*)\"|\\?([^\s;&|<>()]+))")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "fish")
SHELL_OPTIONS_WITH_VALUE = ("-o", "-O", "+o", "+O")
LOOKUPS = ("which", "command", "type", "whence")
KEYWORDS = ("then", "do", "else", "elif", "if", "while", "until", "!", "{")
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
    "watch": ("-n", "-d"),
    "arch": ("-arch",),
    "stdbuf": ("-i", "-o", "-e"),
    "script": ("-F", "-t", "-T"),
}
POSITIONALS_BEFORE_COMMAND = {"timeout": 1, "script": 1}


class _Frame:
    def __init__(self, closer):
        self.closer = closer
        self.quote = None
        self.depth = 0
        self.word = None
        self.words = []
        self.commands = []
        self.heredocs = []

    def end_word(self):
        if self.word is not None:
            self.words.append("".join(self.word))
            self.word = None

    def end_command(self):
        self.end_word()
        if self.words:
            self.commands.append(self.words)
        self.words = []

    def add(self, text):
        if self.word is None:
            self.word = []
        self.word.append(text)


def _looked_up(commands):
    """Returns the program a substitution like $(which x) names, or an empty string."""
    if not commands:
        return ""
    words = commands[-1]
    options = words[1:-1]
    if len(words) >= 2 and words[0] in LOOKUPS and all(w.startswith("-") for w in options):
        return words[-1]
    return ""


def _skip_heredocs(text, i, frame):
    """Moves past the heredoc bodies that start after the newline at i."""
    for delimiter, strip_tabs in frame.heredocs:
        while i < len(text):
            start = i + 1
            end = text.find("\n", start)
            end = len(text) if end == -1 else end
            line = text[start:end]
            body = line.lstrip("\t") if strip_tabs else line
            i = end
            if body == delimiter:
                break
            rest = body[len(delimiter) :].lstrip(" \t")
            if frame.closer and body.startswith(delimiter) and rest.startswith(frame.closer):
                frame.heredocs = []
                return start + len(line) - len(body) + len(delimiter) - 1
    frame.heredocs = []
    return i


def _redirect(text, i, frame):
    """Records a redirection at i and returns the index of its last character."""
    if frame.word is not None and "".join(frame.word).isdigit():
        frame.word = None
    frame.end_word()
    frame.words.append(REDIRECT)
    if text.startswith("<<", i) and not text.startswith("<<<", i):
        match = HEREDOC.match(text, i + 2)
        if match:
            delimiter = next(g for g in match.groups() if g is not None)
            frame.heredocs.append((delimiter, text[i + 2] == "-"))
            frame.words.append(delimiter)
            return match.end() - 1
    while i + 1 < len(text) and text[i + 1] in "<>&|":
        i += 1
    return i


def simple_commands(text):
    """Splits a command line into the word lists of every simple command it runs."""
    frames = [_Frame(None)]
    done = []
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
            frame.end_command()
            done.extend(frames.pop().commands)
            frames[-1].add("\0(" + _looked_up(frame.commands) + "\0)")
        elif c == "#" and frame.word is None:
            end = text.find("\n", i)
            i = (len(text) if end == -1 else end) - 1
        elif c in " \t":
            frame.end_word()
        elif c == "\n":
            frame.end_command()
            i = _skip_heredocs(text, i, frame) if frame.heredocs else i
        elif c == "(":
            frame.depth += 1
            frame.end_command()
        elif c == ")" and frame.depth > 0:
            frame.depth -= 1
            frame.end_command()
        elif c == ")":
            frame.end_word()
            frame.words = []
        elif c in ";&|":
            frame.end_command()
        elif c in "<>":
            i = _redirect(text, i, frame)
        else:
            frame.add(c)
        i += 1
    while frames:
        frame = frames.pop()
        frame.end_command()
        done.extend(frame.commands)
    return done


def _split_command(words):
    """Returns the command word and its arguments, past assignments, redirections and wrappers."""
    i = 0
    while i < len(words):
        word = words[i]
        name = os.path.basename(word)
        if word == REDIRECT:
            i += 2
        elif ASSIGNMENT.match(word) or word in KEYWORDS:
            i += 1
        elif name in WRAPPERS:
            takes_value = WRAPPERS[name]
            i += 1
            while i < len(words) and words[i].startswith("-") and words[i] != "-":
                if name == "command" and words[i] in ("-v", "-V"):
                    return None, []
                i += 2 if words[i] in takes_value else 1
            i += POSITIONALS_BEFORE_COMMAND.get(name, 0)
        else:
            return word, words[i + 1 :]
    return None, []


def _inline_scripts(word, args):
    """Returns the command strings an eval or a shell's -c runs."""
    if word == "eval":
        return [" ".join(args)]
    if os.path.basename(word) not in SHELLS:
        return []
    k = 0
    while k < len(args):
        arg = args[k]
        if arg in SHELL_OPTIONS_WITH_VALUE:
            k += 2
            continue
        if not arg.startswith(("-", "+")):
            return []
        if not arg.startswith("--") and "c" in arg[1:] and k + 1 < len(args):
            return [args[k + 1]]
        k += 1
    return []


def command_words(command):
    """Returns the program every simple command in a command line runs, nested scripts included."""
    found = []
    for words in simple_commands(command):
        word, args = _split_command(words)
        if word is None:
            continue
        looked_up = SUBSTITUTION.fullmatch(word)
        word = looked_up.group(1) if looked_up else word
        found.append(word)
        nested = [word] if re.search(r"\s", word) else _inline_scripts(word, args)
        for script in nested:
            found.extend(command_words(script))
    return found
