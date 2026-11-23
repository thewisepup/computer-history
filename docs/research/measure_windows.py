"""Measure classification windows per day and signal text per window on a dev snapshot.

Read-only. Usage: python -I measure_windows.py <dev history.db> [--tz America/Los_Angeles]
"""

import argparse
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

WINDOW = timedelta(minutes=5)


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def floor5(t: datetime) -> datetime:
    return t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)


@dataclass
class Window:
    not_afk: float = 0.0
    afk: float = 0.0
    signals: Counter[str] = field(default_factory=Counter)
    chars: Counter[str] = field(default_factory=Counter)
    texts: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    titles: set[str] = field(default_factory=set)
    urls: set[str] = field(default_factory=set)
    apps: set[str] = field(default_factory=set)
    domains: set[str] = field(default_factory=set)

    def raw_chars(self) -> int:
        return sum(self.chars.values())

    def dedup_chars(self) -> int:
        distinct = set().union(*self.texts.values()) if self.texts else set()
        return sum(map(len, distinct)) + sum(map(len, self.titles)) + sum(map(len, self.urls))

    def dedup_text_by_source(self, source: str) -> int:
        return sum(map(len, self.texts.get(source, set())))


def spans(start: datetime, end: datetime):
    w = floor5(start)
    while w < end or (w == floor5(start) and start == end):
        yield w, max(start, w), min(end, w + WINDOW)
        if start == end:
            return
        w += WINDOW


def pct(xs: list[int], q: float) -> int:
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--tz", default="America/Los_Angeles")
    args = ap.parse_args()
    tz = ZoneInfo(args.tz)
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    windows: dict[datetime, Window] = defaultdict(Window)

    for started, payload in conn.execute("SELECT started_at, payload FROM observations WHERE source = 'aw-afk'"):
        p = json.loads(payload)
        s = ts(started)
        e = s + timedelta(seconds=p["duration"])
        for w, a, b in spans(s, e):
            secs = (b - a).total_seconds()
            if p["data"]["status"] == "afk":
                windows[w].afk += secs
            else:
                windows[w].not_afk += secs

    rows = conn.execute("SELECT source, started_at, ended_at, app, domain, url, title, text FROM signals")
    for source, started, ended, app, domain, url, title, text in rows:
        s, e = ts(started), ts(ended)
        for w, _, _ in spans(s, e):
            win = windows[w]
            win.signals[source] += 1
            win.chars[source] += len(title or "") + len(url or "") + len(text or "")
            if text:
                win.texts[source].add(text)
            if title:
                win.titles.add(title)
            if url:
                win.urls.add(url)
            if app:
                win.apps.add(app)
            if domain:
                win.domains.add(domain)

    first_text = conn.execute("SELECT min(started_at) FROM signals WHERE source = 'ax-text'").fetchone()[0]
    first_shot = conn.execute("SELECT min(started_at) FROM signals WHERE source = 'screenshot'").fetchone()[0]
    print(f"ax-text from {first_text}; screenshot from {first_shot}\n")

    by_day: dict[str, list[tuple[datetime, Window]]] = defaultdict(list)
    for w, win in windows.items():
        by_day[w.astimezone(tz).date().isoformat()].append((w, win))

    print("day         total  active  fully-afk  no-afk-data(with signals)  empty")
    active_all: list[tuple[datetime, Window]] = []
    for day in sorted(by_day):
        ws = by_day[day]
        active = [(w, x) for w, x in ws if x.not_afk > 0]
        fully_afk = [x for _, x in ws if x.afk > 0 and x.not_afk == 0]
        no_afk = [x for _, x in ws if x.afk == 0 and x.not_afk == 0 and x.signals]
        empty = [x for _, x in ws if x.afk == 0 and x.not_afk == 0 and not x.signals]
        active_all += active
        print(f"{day}  {len(ws):5}  {len(active):6}  {len(fully_afk):9}  {len(no_afk):25}  {len(empty):5}")

    def report(label: str, sample: list[Window]) -> None:
        raw = [x.raw_chars() for x in sample]
        ded = [x.dedup_chars() for x in sample]
        print(f"\n{label}: {len(sample)} active windows")
        print("                         p50     p90     max    mean")
        for name, xs in (("raw chars", raw), ("deduped chars", ded)):
            print(f"  {name:20} {pct(xs, .5):7} {pct(xs, .9):7} {max(xs or [0]):7} {int(statistics.mean(xs or [0])):7}")
        print(f"  ~tokens (deduped / 4)  {pct(ded, .5)//4:7} {pct(ded, .9)//4:7} {max(ded or [0])//4:7} {int(statistics.mean(ded or [0]))//4:7}")
        for src in ("aw-window", "aw-web", "ax-text", "screenshot"):
            n = [x.signals[src] for x in sample]
            c = [x.dedup_text_by_source(src) for x in sample]
            print(f"  {src:11} signals p50 {pct(n, .5):3} p90 {pct(n, .9):3} | deduped text chars p50 {pct(c, .5):6} p90 {pct(c, .9):6}")
        for name, attr in (("apps", "apps"), ("domains", "domains"), ("titles", "titles")):
            xs = [len(getattr(x, attr)) for x in sample]
            print(f"  distinct {name:8} p50 {pct(xs, .5):3} p90 {pct(xs, .9):3} max {max(xs or [0]):3}")

    report("All days (AW only before ax-text started)", [x for _, x in active_all])
    report("Since ax-text started", [x for w, x in active_all if first_text and w >= floor5(ts(first_text))])
    report("Since screenshots started (all sources)", [x for w, x in active_all if first_shot and w >= floor5(ts(first_shot))])


if __name__ == "__main__":
    main()
