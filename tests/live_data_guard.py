"""Move HOME to a throwaway folder and make any touch of the live data folder raise.

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

GUARDED_ENV_VARS = ("COMPUTER_HISTORY_DB", "COMPUTER_HISTORY_SPOOL")
_DATA_FOLDER = Path("Library") / "Application Support" / "ComputerHistory"
LIVE_DATA_DIR = Path(pwd.getpwuid(os.getuid()).pw_dir) / _DATA_FOLDER
_MARKER = _DATA_FOLDER.name.casefold()


class LiveDataTouched(RuntimeError):
    pass


def _roots() -> tuple[str, ...]:
    found = set()
    for home in (LIVE_DATA_DIR.parents[2], Path.home()):
        folder = home / _DATA_FOLDER
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
    if _MARKER not in value.casefold():
        return None
    if event == "sqlite3.connect" and value.startswith("file:"):
        value = urlsplit(value).path
    return os.path.abspath(value).casefold()


def _is_live(path: str) -> bool:
    return any(path == root or path.startswith(root + os.sep) for root in _live_roots)


def _guard(event: str, args: tuple[object, ...]) -> None:
    if event != "open" and event != "sqlite3.connect" and not event.startswith(("os.", "shutil.")):
        return
    for arg in args:
        path = _as_path(arg, event)
        if path is not None and _is_live(path):
            raise LiveDataTouched(f"a test tried to touch live data ({event}): {path}")


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
