from __future__ import annotations

import contextlib
import fcntl
import os
from collections.abc import Generator
from contextlib import contextmanager

from computer_history.stable.layout import Layout


class InstallBusy(Exception):
    """Another install, uninstall, update, rollback or restore holds the stable install's lock."""


@contextmanager
def holding_install_lock(layout: Layout) -> Generator[None]:
    """Hold an exclusive lock on the live folder for the duration, or raise InstallBusy at once.

    A live folder created for the lock is removed again afterwards if it was left empty.
    """
    missing = [folder for folder in (layout.live, *layout.live.parents) if not folder.exists()]
    layout.live.mkdir(parents=True, exist_ok=True)
    held = os.open(layout.live, os.O_RDONLY)
    try:
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InstallBusy(
                "another install, uninstall, update, rollback or restore is using"
                f" {layout.live}; run it again once that one has finished"
            ) from exc
        yield
    finally:
        os.close(held)
        for folder in missing:
            with contextlib.suppress(OSError):
                folder.rmdir()
