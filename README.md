# Computer History: ActivityWatch HTTP proof of concept

> **New here or switching AI assistants?** Start with [AGENTS.md](AGENTS.md):
> product goals, how to run everything (including the ChatGPT tunnel), current
> status and roadmap. This README is the detailed API reference.

Python 3.10+, FastAPI + Uvicorn, no database, no AI classification.
ActivityWatch must be running. Its API remains read-only.

## Run

From this project directory, create an environment and install dependencies:

```sh
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

Start the backend in terminal 1:

```sh
.venv/bin/python history.py serve
```

On Brandon's Mac the verified interpreter is `/opt/homebrew/bin/python3.12`;
the system `python3` is older. Any working Python 3.10+ interpreter is fine.

In terminal 2:

```sh
.venv/bin/python history.py status
.venv/bin/python history.py buckets
.venv/bin/python history.py events --bucket aw-watcher-window_Brandons-MacBook-Pro.local --start 2026-11-12T00:00:00-08:00 --end 2026-11-13T00:00:00-08:00 --limit 5
.venv/bin/python history.py export --bucket aw-watcher-window_Brandons-MacBook-Pro.local --start 2026-11-12T00:00:00-08:00 --end 2026-11-13T00:00:00-08:00
```

Choose an exact bucket from `buckets`. Browser buckets are never automatically combined.
Every client command goes through our backend, not directly to ActivityWatch.
`events` prints JSON; `export` saves JSON and prints the saved payload and absolute file path.
Export filenames are generated uniquely under this project's `output/` directory, which is gitignored.
Use `serve --output-dir /some/path` to change it. Existing files are never overwritten.

Dates must include a timezone. Use consecutive local midnights to request a day.
The raw API's time filtering and event durations are preserved: this is not an
idle-filtered report, and events are not clipped or classified. The end boundary
is passed directly to ActivityWatch; exact boundary behavior is owned by that server.
Omit `--limit` to request all matching events (`-1`). A positive limit is a preview,
and `possibly_truncated` is flagged when the result reaches that limit. Large exports
are buffered in memory; use bounded date ranges for this proof of concept.

## HTTP API

Interactive Swagger documentation: `http://127.0.0.1:8765/docs`; OpenAPI schema: `/openapi.json`.
You can also start with `.venv/bin/uvicorn history:app --host 127.0.0.1 --port 8765`.

Default backend: `http://127.0.0.1:8765`. ActivityWatch: `http://127.0.0.1:5600/api/0`.

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/health` | Check ActivityWatch connectivity and return server info |
| GET | `/buckets` | Return original ActivityWatch bucket metadata |
| GET | `/usage?app=...&start=...&end=...` | Foreground usage totals and original matching events |
| GET | `/events?bucket=...&start=...&end=...&limit=-1` | Fetch raw events in a metadata wrapper |
| POST | `/exports` | Fetch events, save a JSON file, return path and payload |

```sh
curl http://127.0.0.1:8765/health
curl -X POST http://127.0.0.1:8765/exports \
  -H 'Content-Type: application/json' \
  -d '{"bucket":"aw-watcher-window_Brandons-MacBook-Pro.local","start":"2026-11-12T00:00:00-08:00","end":"2026-11-13T00:00:00-08:00","limit":5}'
```

Malformed request bodies, missing fields, and invalid parameter types return 422; invalid date ranges or limit values return 400; ActivityWatch failures return 502. No events and an
unavailable server are different outcomes. The backend binds only to loopback and
is an unauthenticated development server, not a public deployment or MCP server.
Use `serve --port 8766 --aw-url http://127.0.0.1:5600/api/0` to override configuration;
clients use `--server http://127.0.0.1:8766` before their subcommand.

Original event JSON values (including unknown nested fields) are preserved;
JSON whitespace and key formatting are not byte-for-byte preserved. The wrapper
adds source URL, fetch time, request range, bucket metadata, count, and truncation status.

## Tests

```sh
.venv/bin/python -m unittest -v
```

## Next step

### App usage

```sh
curl -G http://127.0.0.1:8765/usage \
  --data-urlencode 'app=ChatGPT' \
  --data-urlencode 'start=2026-11-12T00:00:00-08:00' \
  --data-urlencode 'end=2026-11-13T00:00:00-08:00'
```

Returns `total_seconds`, `total_minutes`, `total_hours`, and original matching
`events`. App names match exactly, ignoring case. The window bucket is discovered
for the ActivityWatch server's hostname; missing/ambiguous buckets return 502.
Totals are foreground time, NOT idle-filtered time, and do not include usage of
a service inside a browser. Totals clip intervals to [start, end) and merge overlaps;
raw event durations remain unchanged. No matches returns zero and an empty list.
For correctness this POC fetches all window events before the end boundary, including
events that started before the requested range. This can be expensive with long histories;
future optimization should preserve overlapping-boundary events.

Add enrichment as a separate transformation of these observations, retaining the
original payload and source identity. CLI and future MCP tools can share the Bridge
service boundary. This POC does not store project labels or calculate active time.

## AI-ready read endpoints

These HTTP endpoints share Python service methods that can later be wrapped by MCP.
They do not perform classification or expose arbitrary SQL.

| Route | Parameters | Result |
| --- | --- | --- |
| `GET /recording-status` | none | Sources, latest event ends, observation age; not a watcher-process health guarantee |
| `GET /apps` | `start`, `end` | Distinct recorded app names |
| `GET /usage/breakdown` | `start`, `end` | Apps ranked by foreground seconds, without raw events |
| `GET /activity/events` | `start`, `end`, optional `app`, `limit` (1–1000, default 100), `offset` | Newest-first original events, filtered before pagination |
| `GET /usage` | `app`, `start`, `end`, optional `include_events`, `event_limit` (1–1000) | Full total with optional bounded evidence |

Usage, app listing, breakdown and activity ranges are limited to 31 days and use
[start, end) with timezone-aware timestamps. They select one window bucket for the
server's host. Missing/ambiguous sources and upstream failures return 502, not zero.
Responses include `observed_seconds`, `unobserved_seconds`, and `coverage_warnings`.
Unobserved time may be sleep, downtime, missing collection, or future time; it is NOT
inferred idle time. Totals are not idle-filtered. Same-app overlaps are unioned;
cross-app overlaps produce a warning in the breakdown. `sum_app_seconds` can then
exceed elapsed observed time. App names match case-insensitively; discovery preserves
original spellings. Pagination is over live data and is not a frozen snapshot.

```sh
curl http://127.0.0.1:8765/recording-status
curl -G http://127.0.0.1:8765/apps --data-urlencode 'start=2026-11-12T00:00:00-08:00' --data-urlencode 'end=2026-11-13T00:00:00-08:00'
curl -G http://127.0.0.1:8765/usage/breakdown --data-urlencode 'start=2026-11-12T00:00:00-08:00' --data-urlencode 'end=2026-11-13T00:00:00-08:00'
curl -G http://127.0.0.1:8765/usage --data-urlencode 'app=ChatGPT' --data-urlencode 'start=2026-11-12T00:00:00-08:00' --data-urlencode 'end=2026-11-13T00:00:00-08:00' --data-urlencode 'include_events=false'
curl -G http://127.0.0.1:8765/activity/events --data-urlencode 'app=ChatGPT' --data-urlencode 'start=2026-11-12T00:00:00-08:00' --data-urlencode 'end=2026-11-13T00:00:00-08:00' --data-urlencode 'limit=5'
```

The legacy bucket-based `/events` and `/exports` remain available. These endpoints
bound AI response sizes but the POC still fetches prior source history internally to
preserve boundary overlaps; very long source histories need a more efficient adapter.
# MCP integration

The same server now exposes a read-only MCP interface using Streamable HTTP at
`http://127.0.0.1:8765/mcp`. Existing REST endpoints still work.

```bash
cd /Users/brandon/workspace/computer-history
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python history.py serve
```

| MCP tool | Arguments | Result |
| --- | --- | --- |
| `get_recording_status` | None | Sources and observation freshness |
| `list_apps` | `start`, `end` | Recorded app names |
| `get_app_usage` | `app`, `start`, `end` | Total foreground usage, without raw events |
| `get_usage_breakdown` | `start`, `end` | Apps ranked by foreground time |
| `get_activity_events` | `start`, `end`, optional `app`, `limit`, `offset` | Original event payloads, newest first |

Use ISO timestamps with timezone offsets, such as `2026-11-12T00:00:00-08:00`.
Ranges are limited to 31 days. Event pages default to 100, with a maximum of
1,000; use the returned `next_offset` for another page. App names use
case-insensitive exact matching. Usage is recorded foreground time, with no idle
filtering. Results include coverage warnings. Tool calls do not write exports
or modify ActivityWatch. All tools share the same backend methods as REST.

To check discovery with the installed official Python MCP client:

```bash
.venv/bin/python - <<'PY'
import asyncio
from mcp import Client

async def main():
    async with Client("http://127.0.0.1:8765/mcp") as client:
        tools = await client.list_tools()
        print([tool.name for tool in tools.tools])
        result = await client.call_tool("get_app_usage", {
            "app": "Notion",
            "start": "2026-11-12T00:00:00-08:00",
            "end": "2026-11-13T00:00:00-08:00",
        })
        print(result.model_dump_json(indent=2))

asyncio.run(main())
PY
```

This implements the server, not the ChatGPT connection. ChatGPT needs a reachable
MCP transport (for example its supported secure tunnel). The local server has
no authentication and keeps the SDK's localhost Host checks. Do not expose the
whole FastAPI server publicly; a remote deployment needs authentication and
explicit trusted-host configuration. No tunnel or ChatGPT account is configured
by this project.

Run tests with `.venv/bin/python -m unittest -q`. They cover MCP discovery,
structured responses, original payload preservation, invalid inputs, upstream
failures, the HTTP mount/lifespan, and the existing REST behavior.

