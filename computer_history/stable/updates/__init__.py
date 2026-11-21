"""Update and rollback: moving the stable install between versions.

updating.py         update: the release-gate walk, then prepare, switch and wait,
    |               or fall back
    +-- preparing.py      build the new version, stop the backend, back up the
    |                     database and place the spool hold; undone on any failure
    +-- waiting.py        wait for the backend's first ok cycle on the new version
    +-- falling_back.py   put the old version back, restoring the backup when the
                          schema changed, then notify

rolling_back.py     rollback: current and previous swapped, the backend restarted
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
