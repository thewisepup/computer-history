"""Seeded, read-only stand-in for the ActivityWatch REST API, for verification runs only.

Serves the endpoints computer-history reads (/info, /buckets/, events, one event)
with the real API's range semantics, plus POST /__chv/advance, which closes the
growing window and AFK events and starts new ones, as a heartbeat would.
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HOST = "chv-fake-aw"
WINDOW = "aw-watcher-window_chv-fake-aw"
AFK = "aw-watcher-afk_chv-fake-aw"
WEB = "aw-watcher-web-chrome_chv-fake-aw"
TYPES = {WINDOW: "currentwindow", AFK: "afkstatus", WEB: "web.tab.current"}

WINDOW_PLAN = [
    ("Cursor", "spool.py — computer-history"),
    ("Google Chrome", "Pull requests · thewisepup/computer-history"),
    ("Cursor", "status.py — computer-history"),
    ("Terminal", "computer-history ingest"),
    ("Google Chrome", "DESIGN.md · computer-history"),
]
WEB_PLAN = [
    ("https://github.com/thewisepup/computer-history/pulls", "Pull requests"),
    ("https://github.com/thewisepup/computer-history/blob/main/docs/DESIGN.md", "DESIGN.md"),
]


class Store:
    def __init__(self, now: datetime) -> None:
        self.lock = threading.Lock()
        self.created = now - timedelta(days=3)
        self.events: dict[str, list[dict]] = {b: [] for b in TYPES}
        self.live: dict[str, int] = {}
        self.next_id = 1
        for day in (3, 2, 1):
            base = now - timedelta(days=day) + timedelta(minutes=5)
            for i, (app, title) in enumerate(WINDOW_PLAN[:3]):
                data = {"app": app, "title": title}
                self._add(WINDOW, base + timedelta(minutes=10 * i), 600, data)
            self._add(AFK, base, 1800, {"status": "not-afk"})
        start = now - timedelta(minutes=40)
        for i in range(8):
            app, title = WINDOW_PLAN[i % len(WINDOW_PLAN)]
            self._add(WINDOW, start + timedelta(minutes=5 * i), 300, {"app": app, "title": title})
        self._add(AFK, start, 2400, {"status": "not-afk"})
        for offset, (url, title) in zip((0, 20), WEB_PLAN, strict=True):
            data = {"url": url, "title": title, "audible": False, "incognito": False, "tabCount": 4}
            self._add(WEB, start + timedelta(minutes=offset), 240, data)
        self.live[WINDOW] = self._add(WINDOW, now, 0, {"app": "Cursor", "title": "live — chv"})
        self.live[AFK] = self._add(AFK, now, 0, {"status": "not-afk"})

    def _add(self, bucket: str, start: datetime, seconds: float, data: dict) -> int:
        event = {"id": self.next_id, "timestamp": start, "duration": seconds, "data": data}
        self.events[bucket].append(event)
        self.next_id += 1
        return event["id"]

    def _view(self, bucket: str, event: dict, now: datetime) -> dict:
        duration = event["duration"]
        if self.live.get(bucket) == event["id"]:
            duration = (now - event["timestamp"]).total_seconds()
        return {**event, "duration": duration}

    def advance(self, now: datetime) -> dict:
        with self.lock:
            closed = {}
            for bucket, event_id in list(self.live.items()):
                event = next(e for e in self.events[bucket] if e["id"] == event_id)
                event["duration"] = (now - event["timestamp"]).total_seconds()
                closed[bucket] = event_id
                data = dict(event["data"])
                if bucket == WINDOW:
                    data["title"] = f"live {self.next_id} — chv"
                self.live[bucket] = self._add(bucket, now, 0, data)
            return {"closed": closed, "live": dict(self.live)}

    def buckets(self) -> dict:
        return {
            b: {
                "id": b,
                "created": self.created.isoformat(),
                "type": t,
                "client": "aw-client-web" if t == "web.tab.current" else b.split("_")[0],
                "hostname": HOST,
                "data": {},
            }
            for b, t in TYPES.items()
        }

    def query(self, bucket: str, start, end, limit: int, now: datetime) -> list[dict]:
        found = []
        with self.lock:
            views = [self._view(bucket, e, now) for e in self.events[bucket]]
        for event in views:
            ts = event["timestamp"]
            te = ts + timedelta(seconds=event["duration"])
            if (start is not None and te < start) or (end is not None and ts > end):
                continue
            if start is not None and ts < start:
                event["duration"] = (te - start).total_seconds()
                event["timestamp"] = ts = start
            if end is not None and te > end:
                event["duration"] = (end - ts).total_seconds()
            found.append(event)
        found.sort(key=lambda e: e["timestamp"], reverse=True)
        return found if limit < 0 else found[:limit]

    def one(self, bucket: str, event_id: str, now: datetime) -> dict | None:
        with self.lock:
            for event in self.events[bucket]:
                if str(event["id"]) == event_id:
                    return self._view(bucket, event, now)
        return None


def _wire(event: dict) -> dict:
    return {**event, "timestamp": event["timestamp"].isoformat()}


def _time(values: list[str]):
    return datetime.fromisoformat(values[0]).astimezone(UTC) if values else None


def handler(store: Store, run_id: str, log: Path):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            now = datetime.now(UTC)
            url = urlparse(self.path)
            parts = [unquote(p) for p in url.path.split("/") if p]
            if parts[:2] != ["api", "0"]:
                return self._send(404, {"message": "not found"})
            rest = parts[2:]
            if rest == ["info"]:
                info = {"hostname": HOST, "version": "chv-fake", "testing": True, "run_id": run_id}
                return self._send(200, info)
            if rest == ["buckets"]:
                return self._send(200, store.buckets())
            if len(rest) >= 3 and rest[0] == "buckets" and rest[1] in TYPES and rest[2] == "events":
                if len(rest) == 4:
                    event = store.one(rest[1], rest[3], now)
                    if event is None:
                        return self._send(404, {"message": "no event"})
                    return self._send(200, _wire(event))
                q = parse_qs(url.query)
                limit = int(q.get("limit", ["-1"])[0])
                start, end = _time(q.get("start", [])), _time(q.get("end", []))
                events = store.query(rest[1], start, end, limit, now)
                return self._send(200, [_wire(e) for e in events])
            return self._send(404, {"message": "not found"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/__chv/advance":
                return self._send(404, {"message": "not found"})
            return self._send(200, store.advance(datetime.now(UTC)))

        def log_message(self, fmt: str, *args) -> None:
            with log.open("a") as f:
                f.write(f"{datetime.now(UTC).isoformat()} {fmt % args}\n")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--port-file", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    store = Store(datetime.now(UTC))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(store, args.run_id, args.log))
    args.port_file.write_text(f"{server.server_port}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
