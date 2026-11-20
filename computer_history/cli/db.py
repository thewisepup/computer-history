from __future__ import annotations

import sys
from pathlib import Path

from computer_history.store import OpenedStore, StoreState


def store_unavailable(store: OpenedStore) -> int:
    """Print why the database cannot be used and return the exit code."""
    print(_unavailable_reason(store), file=sys.stderr)
    if store.state is StoreState.BUSY:
        print(db_busy_hint(store.path), file=sys.stderr)
    return 1


def _unavailable_reason(store: OpenedStore) -> str:
    match store.state:
        case StoreState.MISSING:
            return f"no database at {store.path}; run `computer-history ingest` first"
        case StoreState.OUTDATED:
            return f"cannot read {store.path}: {outdated_note(store)}"
        case StoreState.NEWER:
            return (
                f"cannot use {store.path}: schema v{store.version} is newer than this CLI"
                f" understands (v{store.supported}); upgrade computer-history"
            )
        case StoreState.BUSY | StoreState.UNREADABLE:
            return f"cannot open {store.path}: {store.error}"
        case StoreState.READY:
            raise ValueError(f"{store.path} is ready")


def outdated_note(store: OpenedStore) -> str:
    return (
        f"this CLI uses schema v{store.supported}; `computer-history ingest` will migrate"
        " the database"
    )


def db_busy_hint(db_path: Path) -> str:
    return f"Is another process writing to {db_path}? Try again shortly."
