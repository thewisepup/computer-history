"""The screenshot the capture agent takes with each capture, and whether it keeps the image."""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import NamedTuple

from computer_history.sources import CAPTURE_KIND, DUPLICATE_STATUS, KEPT_STATUS
from computer_history.synthetic.captures import Capture

REMEMBERED_WINDOWS = 12
KEEP_AFTER = timedelta(minutes=10)
SMALLEST_IMAGE_BYTES = 40_000
IMAGE_BYTES_SPREAD = 200_000

Window = tuple[str, str]


class Screenshot(NamedTuple):
    """One capture's screenshot: its status, its window, and the capture whose image it shows."""

    capture: Capture
    status: str
    kept: Capture
    image_bytes: int

    @property
    def window(self) -> Window:
        stretch = self.capture.stretch
        assert stretch is not None
        return stretch.app, stretch.title


@dataclass(frozen=True)
class ScreenshotCounts:
    """The screenshot records by status, and the bytes their kept images hold."""

    statuses: dict[str, int]
    image_bytes: int


def agent_screenshots(captures: list[Capture]) -> list[Screenshot]:
    """The screenshot for every capture of a window, as the agent's per-window dedup decides.

    A frame is a duplicate when its window is among the last dozen kept and still shows the
    same text, until ten minutes after that window's image was kept.
    """
    shots: list[Screenshot] = []
    last_kept: OrderedDict[Window, Capture] = OrderedDict()
    for capture in captures:
        stretch = capture.stretch
        if capture.kind != CAPTURE_KIND or stretch is None:
            continue
        window = (stretch.app, stretch.title)
        kept = last_kept.get(window)
        if (
            kept is not None
            and kept.stretch is not None
            and kept.stretch.text == stretch.text
            and timedelta(0) <= capture.at - kept.at < KEEP_AFTER
        ):
            last_kept.move_to_end(window)
            shots.append(Screenshot(capture, DUPLICATE_STATUS, kept, 0))
            continue
        last_kept[window] = capture
        last_kept.move_to_end(window)
        if len(last_kept) > REMEMBERED_WINDOWS:
            last_kept.popitem(last=False)
        shots.append(Screenshot(capture, KEPT_STATUS, capture, image_bytes(window, capture.at)))
    return shots


def image_bytes(window: Window, at: datetime) -> int:
    """A kept image's size, fixed by its window and capture time."""
    digest = sha256(f"{window[0]}\0{window[1]}\0{at.isoformat()}".encode()).digest()
    return SMALLEST_IMAGE_BYTES + int.from_bytes(digest[:4]) % IMAGE_BYTES_SPREAD


def perceptual_hash(window: Window, text: str) -> str:
    """A frame's 64-bit hash, the same for every frame of one window showing one text."""
    return sha256(f"{window[0]}\0{window[1]}\0{text}".encode()).hexdigest()[:16]


def screenshot_counts(shots: list[Screenshot]) -> ScreenshotCounts:
    """How many screenshot records carry each status, and the bytes the kept ones saved."""
    statuses = Counter(shot.status for shot in shots)
    return ScreenshotCounts(dict(sorted(statuses.items())), sum(shot.image_bytes for shot in shots))
