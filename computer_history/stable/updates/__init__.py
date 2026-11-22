"""Update and rollback: moving the stable install between versions.

updating.py         update: the release-gate walk, then prepare, switch and wait,
    |               or fall back; then swap and check a changed agent, or put
    |               it back; Ctrl-C and SIGTERM interrupt the waits, and each
    |               fallback and the last steps run to their end
    +-- preparing.py      decide whether the capture agent changed, build the new
    |                     version and its agent app (or copy the app unchanged),
    |                     stop the backend, back up the database and place the
    |                     spool hold; undone on any failure
    +-- waiting.py        wait until a deadline for the backend's first ok cycle
    |                     on the new version
    +-- falling_back.py   put the old version back, restoring the backup when the
    |                     schema changed, release the spool hold once the new
    |                     backend is stopped, then notify
    +-- swapping.py       once the backend is through, keep the installed agent
    |                     app in the old version, install the new one over the
    |                     fixed path; or put the old app back, keep the build
    |                     that fell back aside, log and notify
    +-- agent_waiting.py  wait for the swapped-in capture agent's first record,
                          counting only the time aw-afk shows the user active

rolling_back.py     rollback: current and previous swapped, the capture agent
                    moved back first when the previous version can't read its
                    records, and the backend restarted; refused when the
                    previous version cannot open the database's schema
"""

from computer_history.stable.updates.agent_waiting import (
    AGENT_ACTIVE_SECONDS,
    AGENT_WAIT_SECONDS,
    AgentCheck,
)
from computer_history.stable.updates.preparing import UpdateFailed
from computer_history.stable.updates.rolling_back import RollbackFailed, rollback
from computer_history.stable.updates.updating import UpdateReport, update
from computer_history.stable.updates.waiting import FIRST_CYCLE_WAIT_SECONDS

__all__ = [
    "AGENT_ACTIVE_SECONDS",
    "AGENT_WAIT_SECONDS",
    "FIRST_CYCLE_WAIT_SECONDS",
    "AgentCheck",
    "RollbackFailed",
    "UpdateFailed",
    "UpdateReport",
    "rollback",
    "update",
]
