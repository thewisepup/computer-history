from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SPOOL_HOLD_NAME = "spool-deletion-held"


def spool_hold_path(db_path: Path) -> Path:
    """The file beside the database telling ingest to keep spool files until a cycle is ok."""
    return db_path.parent / SPOOL_HOLD_NAME


@dataclass(frozen=True)
class SpoolHold:
    """The hold on spool deletion that update places before restarting the backend."""

    path: Path

    @classmethod
    def beside(cls, db_path: Path) -> SpoolHold:
        return cls(spool_hold_path(db_path))

    @property
    def active(self) -> bool:
        return self.path.exists()

    def place(self) -> None:
        self.path.write_text("")

    def release(self) -> None:
        self.path.unlink(missing_ok=True)
