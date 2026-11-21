"""Move HOME to a throwaway folder and make any touch of the live data or log folder raise.

Importing this installs the guard, so conftest imports it before anything else.
"""

from __future__ import annotations

import atexit
import os
import pwd
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

GUARDED_ENV_VARS = ("COMPUTER_HISTORY_DB", "COMPUTER_HISTORY_SPOOL", "COMPUTER_HISTORY_LOG_DIR")
_DATA_FOLDER = Path("Library") / "Application Support" / "ComputerHistory"
_LOG_FOLDER = Path("Library") / "Logs" / "computer-history"
_REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
LIVE_DATA_DIR = _REAL_HOME / _DATA_FOLDER
LIVE_LOG_DIR = _REAL_HOME / _LOG_FOLDER
_MARKERS = tuple(folder.name.casefold() for folder in (_DATA_FOLDER, _LOG_FOLDER))


class LiveDataTouched(RuntimeError):
    pass


class RealNotification(RuntimeError):
    pass


def _roots() -> tuple[str, ...]:
    found = set()
    for home in (_REAL_HOME, Path.home()):
        for folder in (home / _DATA_FOLDER, home / _LOG_FOLDER):
            found.add(os.path.abspath(folder).casefold())
            found.add(os.path.realpath(folder).casefold())
    return tuple(found)


_live_roots = _roots()


def _as_path(value: object, event: str) -> str | None:
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    if not isinstance(value, str):
        return None
    value = unquote(value)
    if not any(marker in value.casefold() for marker in _MARKERS):
        return None
    if event == "sqlite3.connect" and value.startswith("file:"):
        value = urlsplit(value).path
    return os.path.abspath(value).casefold()


def _is_live(path: str) -> bool:
    return any(path == root or path.startswith(root + os.sep) for root in _live_roots)


def _guard(event: str, args: tuple[object, ...]) -> None:
    if event == "subprocess.Popen" and _posts_notification(args):
        raise RealNotification(f"a test tried to post a real notification: {args[1]!r}")
    if event != "open" and event != "sqlite3.connect" and not event.startswith(("os.", "shutil.")):
        return
    for arg in args:
        path = _as_path(arg, event)
        if path is not None and _is_live(path):
            raise LiveDataTouched(f"a test tried to touch live data ({event}): {path}")


def _posts_notification(args: tuple[object, ...]) -> bool:
    command = args[1] if len(args) > 1 else None
    if isinstance(command, list | tuple) and command:
        return os.path.basename(str(command[0])) == "osascript"
    return False


def install() -> Path:
    """Sandbox HOME and arm the audit hook; returns the sandbox folder."""
    sandbox = Path(tempfile.mkdtemp(prefix="computer-history-test-home-"))
    os.environ["HOME"] = str(sandbox)
    for name in GUARDED_ENV_VARS:
        os.environ.pop(name, None)
    sys.addaudithook(_guard)
    atexit.register(shutil.rmtree, sandbox, ignore_errors=True)
    return sandbox


SANDBOX_HOME = install()
