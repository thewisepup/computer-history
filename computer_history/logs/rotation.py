from __future__ import annotations

import fcntl
import logging
import logging.handlers
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from io import TextIOWrapper
from pathlib import Path


class SharedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A size-rotated log file that several processes append to at once.

    Each record is written under a lock file, after reopening the log if another process rotated it.
    """

    def __init__(self, path: Path, *, max_bytes: int, backups: int) -> None:
        super().__init__(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        self._lock = path.with_name(f"{path.name}.lock").open("a")
        self._failed = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record) + self.terminator
            with self._locked():
                stream = self._follow()
                size = os.fstat(stream.fileno()).st_size
                if size and size + len(line.encode("utf-8")) > self.maxBytes:
                    self.doRollover()
                    stream = self._follow()
                stream.write(line)
                stream.flush()
        except Exception:
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        if self._failed:
            return
        self._failed = True
        error = sys.exc_info()[1]
        sys.stderr.write(f"computer-history: cannot write {self.baseFilename}: {error}\n")

    def close(self) -> None:
        super().close()
        self._lock.close()

    @contextmanager
    def _locked(self) -> Generator[None]:
        fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)

    def _follow(self) -> TextIOWrapper:
        try:
            current = os.stat(self.baseFilename).st_ino
        except FileNotFoundError:
            current = None
        stream: TextIOWrapper | None = self.stream
        if stream is not None and current == os.fstat(stream.fileno()).st_ino:
            return stream
        if stream is not None:
            stream.close()
            self.stream = None
        stream = self.stream = self._open()
        return stream
