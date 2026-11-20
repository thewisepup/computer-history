from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable

NOTIFY_ENV_VAR = "COMPUTER_HISTORY_NOTIFY"
NOTIFY_TIMEOUT_SECONDS = 5
NOTIFICATION_TITLE = "Computer History"

log = logging.getLogger(__name__)


def desktop_notifier() -> Callable[[str], None] | None:
    """The macOS notification sender, or None when $COMPUTER_HISTORY_NOTIFY is 0."""
    return None if os.environ.get(NOTIFY_ENV_VAR) == "0" else post_notification


def post_notification(text: str) -> None:
    """Show the text as a macOS notification, giving up quietly if it cannot."""
    script = f"display notification {_quoted(text)} with title {_quoted(NOTIFICATION_TITLE)}"
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=NOTIFY_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("notification not shown", extra={"error": str(exc)})


def _quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
