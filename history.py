"""Local ActivityWatch FastAPI bridge and CLI."""
import argparse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn
from history_mcp import create_mcp

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PROJECT_DIR / "output"
DEFAULT_AW_URL = "http://127.0.0.1:5600/api/0"
LOG = logging.getLogger("computer_history.http")

# `serve --reload` runs the app in a subprocess that re-imports this module on every
# edit, so it cannot see the parent's parsed arguments. These carry them across.
ENV_AW_URL = "COMPUTER_HISTORY_AW_URL"
ENV_OUTPUT_DIR = "COMPUTER_HISTORY_OUTPUT_DIR"
ENV_LOG_LEVEL = "COMPUTER_HISTORY_LOG_LEVEL"


def configure_logging(level="INFO"):
    """Send our own logs to stderr, independent of whatever configured the root logger."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s"))
    logger = logging.getLogger("computer_history")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(str(level).upper())
    logger.propagate = False


class UpstreamError(Exception):
    pass


def request_json(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise UpstreamError(f"HTTP {exc.code} from {urlsplit(url).netloc}: "
                            f"{exc.read(2048).decode(errors='replace')}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise UpstreamError(f"Request failed: {exc}") from exc


def parse_timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Dates must be ISO timestamps with a timezone, e.g. 2026-11-12T00:00:00-08:00") from exc
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone offset or Z")
    return result


def event_interval(event):
    try:
        begin = parse_timestamp(event["timestamp"])
        duration = float(event["duration"])
        if duration < 0:
            raise ValueError("Negative duration")
        return begin, begin + timedelta(seconds=duration)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise UpstreamError("Invalid timestamp or duration in ActivityWatch event") from exc


def union_seconds(intervals):
    merged = []
    for left, right in sorted(intervals):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return sum((right - left).total_seconds() for left, right in merged)


class Bridge:
    def __init__(self, aw_url, output_dir):
        self.aw_url = aw_url.rstrip("/")
        self.output_dir = Path(output_dir)

    def status(self):
        return {"status": "ok", "activitywatch": request_json(self.aw_url + "/info")}

    def buckets(self):
        return request_json(self.aw_url + "/buckets/")

    def recording_status(self):
        info = request_json(self.aw_url + "/info")
        sources = []
        now = datetime.now(timezone.utc)
        for bucket, metadata in self.buckets().items():
            events = request_json(self.aw_url + "/buckets/" + quote(bucket, safe="") + "/events?limit=1")
            latest = None
            if events:
                begin, finish = event_interval(events[0])
                latest = finish
            sources.append({"bucket": bucket, "type": metadata.get("type"),
                            "hostname": metadata.get("hostname"),
                            "latest_observation_end": latest.isoformat() if latest else None,
                            "seconds_since_observation": max(0, (now - latest).total_seconds()) if latest else None})
        return {"activitywatch": info, "checked_at": now.isoformat(), "sources": sources,
                "note": "Observation timestamps indicate freshness, not proof that a watcher is running."}

    def window_data(self, start, end):
        start_time, end_time = parse_timestamp(start), parse_timestamp(end)
        if start_time >= end_time:
            raise ValueError("start must precede end")
        if end_time - start_time > timedelta(days=31):
            raise ValueError("Usage and activity requests are limited to 31 days")
        info = request_json(self.aw_url + "/info")
        candidates = [key for key, value in self.buckets().items()
                      if value.get("type") == "currentwindow"
                      and value.get("hostname") == info.get("hostname")]
        if len(candidates) != 1:
            raise UpstreamError("Expected exactly one window bucket for the ActivityWatch host; "
                                f"found {len(candidates)}")
        bucket = candidates[0]
        # Include events starting before the range that may overlap its boundary.
        query = urlencode({"end": end, "limit": -1})
        raw = request_json(self.aw_url + "/buckets/" + quote(bucket, safe="") + "/events?" + query)
        if not isinstance(raw, list):
            raise UpstreamError("ActivityWatch returned an unexpected events response")
        rows = []
        for event in raw:
            begin, finish = event_interval(event)
            left, right = max(start_time, begin), min(end_time, finish)
            if left < right or (begin == finish and start_time <= begin < end_time):
                rows.append((event, left, right))
        covered = union_seconds([(left, right) for _, left, right in rows if left < right])
        missing = max(0, (end_time - start_time).total_seconds() - covered)
        return {"start": start, "end": end, "bucket": bucket,
                "measurement": "recorded foreground time; not idle-filtered", "idle_filtered": False,
                "observed_seconds": covered, "unobserved_seconds": missing,
                "coverage_warnings": (["No foreground observations in this range."] if not rows else
                                      ["Some requested time has no foreground observations; it is not necessarily idle time."] if missing > 0 else [])}, rows

    def usage(self, app, start, end, include_events=True, event_limit=None):
        if not app.strip():
            raise ValueError("app must not be blank")
        context, rows = self.window_data(start, end)
        rows = [row for row in rows if str(row[0].get("data", {}).get("app", "")).casefold() == app.strip().casefold()]
        seconds = union_seconds([(left, right) for _, left, right in rows if left < right])
        events = [row[0] for row in rows]
        shown = events[:event_limit] if include_events else []
        return {**context, "app": app.strip(), "total_seconds": seconds,
                "total_minutes": seconds / 60, "total_hours": seconds / 3600,
                "matching": "case-insensitive exact app name", "event_count": len(events),
                "returned_event_count": len(shown), "events_truncated": len(shown) < len(events), "events": shown}

    def list_apps(self, start, end):
        context, rows = self.window_data(start, end)
        names = sorted({row[0].get("data", {}).get("app") for row in rows
                        if isinstance(row[0].get("data", {}).get("app"), str)},
                       key=lambda name: (name.casefold(), name))
        return {**context, "apps": names, "app_count": len(names)}

    def breakdown(self, start, end):
        context, rows = self.window_data(start, end)
        groups = {}
        for event, left, right in rows:
            name = event.get("data", {}).get("app") or "Unknown"
            group = groups.setdefault(name.casefold(), {"app": name, "intervals": [], "event_count": 0})
            group["event_count"] += 1
            if left < right:
                group["intervals"].append((left, right))
        apps = []
        for group in groups.values():
            seconds = union_seconds(group.pop("intervals"))
            apps.append({**group, "total_seconds": seconds, "total_minutes": seconds / 60})
        apps.sort(key=lambda item: (-item["total_seconds"], item["app"].casefold()))
        total = sum(item["total_seconds"] for item in apps)
        if total > context["observed_seconds"] + 0.000001:
            context["coverage_warnings"].append("Different apps have overlapping source intervals; app totals are not additive elapsed time.")
        return {**context, "apps": apps, "app_count": len(apps), "sum_app_seconds": total}

    def activity_events(self, start, end, app=None, limit=100, offset=0):
        if app is not None and not app.strip():
            raise ValueError("app must not be blank")
        context, rows = self.window_data(start, end)
        events = [event for event, _, _ in rows if app is None or
                  str(event.get("data", {}).get("app", "")).casefold() == app.strip().casefold()]
        events.sort(key=lambda event: parse_timestamp(event["timestamp"]), reverse=True)
        shown = events[offset:offset + limit]
        more = offset + len(shown) < len(events)
        return {**context, "event_count": len(events), "returned_event_count": len(shown),
                "offset": offset, "limit": limit, "has_more": more,
                "next_offset": offset + limit if more else None, "events": shown}

    def events(self, options):
        bucket = options.get("bucket")
        if not isinstance(bucket, str) or not bucket.strip():
            raise ValueError("An explicit bucket is required")
        start, end = options.get("start"), options.get("end")
        if parse_timestamp(start) >= parse_timestamp(end):
            raise ValueError("start must precede end")
        try:
            limit = int(options.get("limit", -1))
        except (ValueError, TypeError) as exc:
            raise ValueError("limit must be -1 (all events) or a positive integer") from exc
        if limit != -1 and limit < 1:
            raise ValueError("limit must be -1 (all events) or a positive integer")
        query = urlencode({"start": start, "end": end, "limit": limit})
        bucket_path = self.aw_url + "/buckets/" + quote(bucket, safe="")
        metadata = request_json(bucket_path)
        events = request_json(bucket_path + "/events?" + query)
        if not isinstance(events, list):
            raise UpstreamError("ActivityWatch returned an unexpected events response")
        return {
            "source": "activitywatch", "source_url": self.aw_url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "request": {"bucket": bucket, "start": start, "end": end, "limit": limit},
            "bucket": metadata, "event_count": len(events),
            "possibly_truncated": limit > 0 and len(events) >= limit,
            "events": events,
        }

    def export(self, options):
        result = self.events(options)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        name = datetime.now(timezone.utc).strftime("activitywatch-%Y%m%dT%H%M%SZ-") + uuid4().hex[:8] + ".json"
        target = self.output_dir / name
        # Exclusive creation prevents accidental overwrites; keep history private to this user.
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        return {"output_file": str(target.resolve()), "data": result}


class ExportRequest(BaseModel):
    bucket: str = Field(min_length=1)
    start: str = Field(description="ISO timestamp with timezone")
    end: str = Field(description="ISO timestamp with timezone")
    limit: int = Field(default=-1, description="-1 for all matching events; positive for preview")


def create_app(aw_url=DEFAULT_AW_URL, output_dir=DEFAULT_OUTPUT):
    bridge = Bridge(aw_url, output_dir)
    mcp = create_mcp(bridge)
    mcp_app = mcp.streamable_http_app(stateless_http=True, json_response=True)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Computer History", version="0.1.0",
                  description="Read ActivityWatch events and export original payloads to JSON.",
                  lifespan=lifespan)

    # One line per HTTP request. MCP tool names and arguments live in the JSON-RPC body,
    # so they are logged per tool in history_mcp.py; this only records the transport call.
    @app.middleware("http")
    async def log_request(request, call_next):
        transport = "MCP" if request.url.path.rstrip("/") == "/mcp" else "REST"
        level = logging.DEBUG if transport == "MCP" else logging.INFO
        target = request.url.path + (("?" + request.url.query) if request.url.query else "")
        LOG.log(level, "%s %s %s", transport, request.method, target)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            LOG.warning("%s %s %s failed after %.0fms: %s: %s", transport, request.method,
                        target, (time.perf_counter() - started) * 1000, type(exc).__name__, exc)
            raise
        LOG.log(level, "%s %s %s -> %s in %.0fms", transport, request.method, target,
                response.status_code, (time.perf_counter() - started) * 1000)
        return response

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(UpstreamError)
    async def upstream_failure(request, exc):
        return JSONResponse(status_code=502, content={"error": str(exc)})

    @app.exception_handler(OSError)
    async def write_failure(request, exc):
        return JSONResponse(status_code=500, content={"error": "Could not write export; check output directory permissions"})

    # Sync endpoints run blocking ActivityWatch/file operations in FastAPI's thread pool.
    @app.get("/health", summary="Check backend and ActivityWatch connectivity")
    def health():
        return bridge.status()

    @app.get("/buckets", summary="List ActivityWatch data sources")
    def buckets():
        return bridge.buckets()

    @app.get("/events", summary="Fetch original event payloads")
    def events(bucket: str, start: str, end: str, limit: int = -1):
        return bridge.events({"bucket": bucket, "start": start, "end": end, "limit": limit})

    @app.post("/exports", summary="Fetch and save a JSON export")
    def export(options: ExportRequest):
        return bridge.export(options.model_dump())

    @app.get("/usage", summary="Get foreground app usage and original matching events")
    def usage(app: str, start: str, end: str, include_events: bool = True,
              event_limit: int | None = Query(default=None, ge=1, le=1000)):
        return bridge.usage(app, start, end, include_events, event_limit)

    @app.get("/recording-status", summary="Inspect data sources and observation freshness")
    def recording_status():
        return bridge.recording_status()

    @app.get("/apps", summary="List recorded apps in a time range")
    def list_apps(start: str, end: str):
        return bridge.list_apps(start, end)

    @app.get("/usage/breakdown", summary="Rank apps by recorded foreground time")
    def breakdown(start: str, end: str):
        return bridge.breakdown(start, end)

    @app.get("/activity/events", summary="Inspect paginated foreground evidence, optionally by app")
    def activity_events(start: str, end: str, app: str | None = None,
                        limit: int = Query(default=100, ge=1, le=1000),
                        offset: int = Query(default=0, ge=0)):
        return bridge.activity_events(start, end, app, limit, offset)

    # Mount last so REST routes retain precedence; the child serves /mcp exactly.
    app.mount("/", mcp_app)
    return app


# Import-time app for `uvicorn history:app` and for `serve --reload` workers. Logging is
# configured only when asked through the environment, so importing this module in tests
# stays quiet.
if os.environ.get(ENV_LOG_LEVEL):
    configure_logging(os.environ[ENV_LOG_LEVEL])
app = create_app(os.environ.get(ENV_AW_URL, DEFAULT_AW_URL),
                 os.environ.get(ENV_OUTPUT_DIR, DEFAULT_OUTPUT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8765", help="Our backend URL")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the local HTTP backend")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--aw-url", default=DEFAULT_AW_URL)
    serve.add_argument("--reload", action="store_true",
                       help="Restart the server when a .py file in this project changes (development)")
    serve.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    serve.add_argument("--log-level", default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="DEBUG also logs each MCP transport request")
    sub.add_parser("status", help="Check backend and ActivityWatch connectivity")
    sub.add_parser("buckets", help="Print ActivityWatch buckets")
    for name in ("events", "export"):
        command = sub.add_parser(name, help="Print events" if name == "events" else "Save and print events")
        command.add_argument("--bucket", required=True)
        command.add_argument("--start", required=True, help="ISO timestamp including timezone")
        command.add_argument("--end", required=True, help="ISO timestamp including timezone")
        command.add_argument("--limit", type=int, default=-1, help="-1 fetches all matching events")
    args = parser.parse_args()
    if args.command == "serve":
        configure_logging(args.log_level)
        options = {"host": "127.0.0.1", "port": args.port, "log_level": args.log_level.lower()}
        if not args.reload:
            uvicorn.run(create_app(args.aw_url, args.output_dir), **options)
            return
        # Reloading re-imports this module in a worker process, so the app has to be named
        # by import string and configured through the environment rather than built here.
        os.environ[ENV_AW_URL] = args.aw_url
        os.environ[ENV_OUTPUT_DIR] = str(args.output_dir)
        os.environ[ENV_LOG_LEVEL] = args.log_level
        uvicorn.run("history:app", reload=True, reload_dirs=[str(PROJECT_DIR)], **options)
        return
    base = args.server.rstrip("/")
    try:
        if args.command in ("status", "buckets"):
            result = request_json(base + ("/health" if args.command == "status" else "/buckets"))
        else:
            options = {key: getattr(args, key) for key in ("bucket", "start", "end", "limit")}
            result = (request_json(base + "/exports", options) if args.command == "export"
                      else request_json(base + "/events?" + urlencode(options)))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except UpstreamError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
