"""Keep every test run away from the live database, spool and agent folder.

conftest installs this once, before any test runs, and it holds for the whole
process, including mutmut's mutant runs and any CLI subprocess a test starts:

- HOME moves to a throwaway folder, so every default path (database, spool,
  agent settings, dataset cache) lands there, and $COMPUTER_HISTORY_DB and
  $COMPUTER_HISTORY_SPOOL are cleared.
- An audit hook makes any open, SQLite connect, delete, rename or mkdir under
  the real data folder raise LiveDataTouched, whatever path the code computed.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

LIVE_DATA_DIR = Path.home() / "Library" / "Application Support" / "ComputerHistory"
GUARDED_ENV_VARS = ("COMPUTER_HISTORY_DB", "COMPUTER_HISTORY_SPOOL")
_MARKER = "ComputerHistory"
_live_roots = (os.path.abspath(LIVE_DATA_DIR), os.path.realpath(LIVE_DATA_DIR))


class LiveDataTouched(RuntimeError):
    pass


def _as_path(value: object, event: str) -> str | None:
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    if not isinstance(value, str) or _MARKER not in value:
        return None
    if event == "sqlite3.connect" and value.startswith("file:"):
        value = unquote(value[len("file:") :].split("?", 1)[0])
    return os.path.abspath(value)


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
    return sandbox


def remove(sandbox: Path) -> None:
    shutil.rmtree(sandbox, ignore_errors=True)
