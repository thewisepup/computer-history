"""Any AWApi served over the ActivityWatch REST endpoints on loopback, for end-to-end tests."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from computer_history.sources import AWApi

LOOPBACK = "127.0.0.1"


def aw_server(api: AWApi) -> ThreadingHTTPServer:
    """An HTTP server for the API bound to an ephemeral loopback port, not yet serving."""
    return ThreadingHTTPServer((LOOPBACK, 0), _handler(api))


@contextmanager
def served_over_http(api: AWApi) -> Iterator[str]:
    """Serve the API on an ephemeral loopback port and yield its base URL until the block ends."""
    server = aw_server(api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.socket.getsockname()[:2]
        yield f"http://{host}:{port}/api/0"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _handler(api: AWApi) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlparse(self.path)
            parts = [unquote(part) for part in url.path.split("/") if part]
            if parts[:2] != ["api", "0"]:
                return self._send(404, {"message": "not found"})
            match parts[2:]:
                case ["info"]:
                    return self._send(200, {"hostname": "aw-http", "testing": True})
                case ["buckets"]:
                    return self._send(200, api.get_buckets())
                case ["buckets", bucket, "events"] if bucket in api.get_buckets():
                    query = parse_qs(url.query)
                    found = api.get_events(
                        bucket,
                        start=_time(query.get("start")),
                        end=_time(query.get("end")),
                        limit=int(query.get("limit", ["-1"])[0]),
                    )
                    return self._send(200, found)
                case ["buckets", bucket, "events", event_id] if bucket in api.get_buckets():
                    event = api.get_event(bucket, int(event_id) if event_id.isdigit() else event_id)
                    if event is None:
                        return self._send(404, {"message": "no such event"})
                    return self._send(200, event)
            return self._send(404, {"message": "not found"})

        def _send(self, code: int, body: Any) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def _time(values: list[str] | None) -> datetime | None:
    return datetime.fromisoformat(values[0]).astimezone(UTC) if values else None
