"""Update and rollback: moving the stable install between versions.

updating.py         update: the release-gate walk, then prepare, switch and wait,
    |               or fall back; Ctrl-C and SIGTERM interrupt it until the
    |               fallback or the last steps, which run to their end
    +-- preparing.py      decide whether the capture agent changed, build the new
    |                     version and its agent app (or copy the app unchanged),
    |                     stop the backend, back up the database and place the
    |                     spool hold; undone on any failure
    +-- waiting.py        wait until a deadline for the backend's first ok cycle
    |                     on the new version
    +-- falling_back.py   put the old version back, restoring the backup when the
                          schema changed, release the spool hold once the new
                          backend is stopped, then notify

rolling_back.py     rollback: current and previous swapped and the backend
                    restarted, refused when the previous version cannot open
                    the database's schema
"""

from computer_history.stable.updates.preparing import UpdateFailed
from computer_history.stable.updates.rolling_back import RollbackFailed, rollback
from computer_history.stable.updates.updating import UpdateReport, update
from computer_history.stable.updates.waiting import FIRST_CYCLE_WAIT_SECONDS

__all__ = [
    "FIRST_CYCLE_WAIT_SECONDS",
    "RollbackFailed",
    "UpdateFailed",
    "UpdateReport",
    "rollback",
    "update",
]
