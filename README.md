# Computer History

A local activity layer that any AI assistant can query. It takes raw capture
from [ActivityWatch](https://activitywatch.net/) and, eventually, attributes
it to projects and types of work.

> **New here or switching AI assistants?** Start with [AGENTS.md](AGENTS.md).
> The design is in [docs/DESIGN.md](docs/DESIGN.md), the milestones in
> [docs/milestones.md](docs/milestones.md), and the product requirements in
> [docs/PRD.md](docs/PRD.md). Connecting ChatGPT is covered by the
> `connect-chatgpt` skill (`.claude/skills/connect-chatgpt/`).

The repo holds two separate programs that share nothing at runtime:

| | What it is | Entry point | Reads from |
| --- | --- | --- | --- |
| **Activity store** (the rewrite, M1 done) | Ingests ActivityWatch events into a local SQLite store and reports on it | `computer-history` → `computer_history/` | ActivityWatch, then its own SQLite DB |
| **POC server** (frozen until M6) | Read-only REST + MCP server for AI clients | `history.py`, `history_mcp.py` | ActivityWatch, live on every request |

The POC does not read the SQLite store yet. M6 replaces it with MCP tools
built on the store.

Both programs are read-only toward ActivityWatch, bind only to loopback, and
have no authentication.

## Setup

You need Python 3.11+ and a running ActivityWatch server
(`http://127.0.0.1:5600/api/0`). On Brandon's Mac the verified interpreter is
`/opt/homebrew/bin/python3.12`. The system `python3` there is too old.

```sh
brew install gitleaks
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test,dev]'
git config core.hooksPath .githooks
```

This installs two console scripts into `.venv/bin/`: `computer-history` (the
store CLI) and `history` (the POC, the same as `python history.py`).

## Activity store: `computer-history`

```sh
.venv/bin/computer-history backfill --dry-run   # plan a one-time import of existing history
.venv/bin/computer-history backfill             # run it
.venv/bin/computer-history ingest --watch       # keep ingesting settled events every 60s
.venv/bin/computer-history status               # freshness, coverage gaps, row counts
.venv/bin/computer-history rebuild-signals      # regenerate derived signals from observations
```

Raw events go into an immutable `observations` table, and normalized
`signals` are derived from them, so signals can always be rebuilt. The
database defaults to `~/Library/Application Support/ComputerHistory-dev/history.db`
for a run from a checkout (dev) and to `ComputerHistory/history.db`, the live
one, for the stable install; dev is refused the live one. Override it with
`--db-path` or `$COMPUTER_HISTORY_DB`. The networked commands
take `--aw-url`.

[computer_history/cli/README.md](computer_history/cli/README.md) documents
every command with sample output. Each package's `__init__.py` begins with a
diagram of how data flows through it.

## POC server: `history.py`

FastAPI + Uvicorn with no database and no classification. Every request goes
to ActivityWatch live.

### Run

```sh
.venv/bin/python history.py serve            # http://127.0.0.1:8765
.venv/bin/python history.py serve --reload   # restart when a .py file in this directory changes
```

`serve` takes `--port` (default 8765), `--aw-url`, `--output-dir` (default
`output/`, gitignored) and `--log-level` (`DEBUG`/`INFO`/`WARNING`/`ERROR`).
You can also start it with
`.venv/bin/uvicorn history:app --host 127.0.0.1 --port 8765`. That form reads
its settings from `COMPUTER_HISTORY_AW_URL`, `COMPUTER_HISTORY_OUTPUT_DIR` and
`COMPUTER_HISTORY_LOG_LEVEL`. `serve --reload` passes its flags to the reload
worker through those same variables.

Without `--reload`, the process keeps serving the code it imported at startup,
so you have to restart it after edits. Reloading restarts the whole worker:

- In-flight requests are dropped.
- A syntax error leaves the old worker serving until the file parses again.
- Only `.py` files trigger a reload, so writing exports into `output/` does
  not.

Turn off `--reload` when ChatGPT is connected through the tunnel. Reloading
uses `watchfiles` from the `dev` extra. Without it, uvicorn falls back to
slower polling.

### CLI client

The other subcommands are clients of the running server. They never call
ActivityWatch directly.

```sh
.venv/bin/python history.py status
.venv/bin/python history.py buckets
.venv/bin/python history.py events --bucket aw-watcher-window_Brandons-MacBook-Pro.local --start 2026-11-12T00:00:00-08:00 --end 2026-11-13T00:00:00-08:00 --limit 5
.venv/bin/python history.py export --bucket aw-watcher-window_Brandons-MacBook-Pro.local --start 2026-11-12T00:00:00-08:00 --end 2026-11-13T00:00:00-08:00
```

- Pick an exact bucket name from the `buckets` output. Browser buckets are
  never combined automatically.
- `events` prints JSON.
- `export` saves the result to a uniquely named file under the output
  directory, then prints the payload and the file's absolute path. Existing
  files are never overwritten.
- If the server runs on another port, put `--server http://127.0.0.1:8766`
  before the subcommand.

### Call logging

The serving terminal logs every call to stderr, so you can see what an AI
client is doing:

```
2026-11-12 14:28:07,512 INFO    computer_history.http REST GET /apps?start=...&end=...
2026-11-12 14:28:07,583 INFO    computer_history.http REST GET /apps?start=...&end=... -> 200 in 71ms
2026-11-12 14:28:07,601 INFO    computer_history.mcp.tool MCP tool call get_activity_events(start='...', end='...', app='Google Chrome', limit=5, offset=0)
2026-11-12 14:28:07,635 INFO    computer_history.mcp.tool MCP tool ok get_activity_events in 34ms
```

- **REST** calls are logged with their query string, once when they arrive
  and once when they finish.
- **MCP** calls are logged per tool, with every argument, including defaults
  the client did not send. This is needed because tool names and arguments
  travel inside the JSON-RPC body of a single `POST /mcp`. Argument values
  longer than 120 characters are truncated.
- **Failures** log one warning line naming the call and the error.

`--log-level DEBUG` also logs each MCP transport request (`POST /mcp` itself,
including handshake traffic). `--log-level WARNING` logs only failures.

### REST API

Interactive docs are at `http://127.0.0.1:8765/docs`, and the OpenAPI schema
is at `/openapi.json`.

| Method | Route | Parameters | Result |
| --- | --- | --- | --- |
| GET | `/health` | none | Checks ActivityWatch connectivity and returns its `/info` |
| GET | `/buckets` | none | Original ActivityWatch bucket metadata |
| GET | `/recording-status` | none | Each source's latest event end and the time since then. This shows freshness, not watcher-process health |
| GET | `/apps` | `start`, `end` | Distinct recorded app names |
| GET | `/usage` | `app`, `start`, `end`, optional `include_events` (default true), `event_limit` (1–1000) | Foreground total for one app, with matching events as evidence |
| GET | `/usage/breakdown` | `start`, `end` | Apps ranked by foreground seconds, without raw events |
| GET | `/activity/events` | `start`, `end`, optional `app`, `limit` (1–1000, default 100), `offset` | Original events, newest first, filtered before pagination |
| GET | `/events` | `bucket`, `start`, `end`, optional `limit` (default −1 = all) | Raw events from one bucket, in a metadata wrapper |
| POST | `/exports` | JSON body `{bucket, start, end, limit}` | Same as `/events`, also saved to a JSON file. Returns `output_file` and `data` |

```sh
curl http://127.0.0.1:8765/recording-status
curl -G http://127.0.0.1:8765/usage/breakdown --data-urlencode 'start=2026-11-12T00:00:00-08:00' --data-urlencode 'end=2026-11-13T00:00:00-08:00'
curl -G http://127.0.0.1:8765/usage --data-urlencode 'app=ChatGPT' --data-urlencode 'start=2026-11-12T00:00:00-08:00' --data-urlencode 'end=2026-11-13T00:00:00-08:00' --data-urlencode 'include_events=false'
curl -G http://127.0.0.1:8765/activity/events --data-urlencode 'app=ChatGPT' --data-urlencode 'start=2026-11-12T00:00:00-08:00' --data-urlencode 'end=2026-11-13T00:00:00-08:00' --data-urlencode 'limit=5'
curl -X POST http://127.0.0.1:8765/exports -H 'Content-Type: application/json' \
  -d '{"bucket":"aw-watcher-window_Brandons-MacBook-Pro.local","start":"2026-11-12T00:00:00-08:00","end":"2026-11-13T00:00:00-08:00","limit":5}'
```

**Errors.** No events and an unreachable server are different outcomes.

| Status | When |
| --- | --- |
| 422 | Malformed bodies, missing fields, wrong parameter types, out-of-range `limit`/`event_limit`/`offset` |
| 400 | Invalid timestamps or ranges, a blank `app`, an invalid `/events` limit |
| 502 | ActivityWatch failed, or there are zero or several window buckets for its host |
| 500 | An export could not be written |

**Timestamps.** Every timestamp needs a timezone, for example
`2026-11-12T00:00:00-08:00`. To request one day, use two consecutive local
midnights.

**App endpoints** (`/apps`, `/usage`, `/usage/breakdown`, `/activity/events`):

- **Range.** Limited to 31 days and treated as `[start, end)`.
- **Bucket.** Each request uses the single `currentwindow` bucket whose
  hostname matches the ActivityWatch server.
- **Totals.** Totals are recorded foreground time, not idle-filtered. They
  don't count time spent in a service inside a browser. Intervals are clipped
  to the range, and overlaps within one app are merged. The raw event
  durations in responses are unchanged.
- **Coverage.** Responses include `observed_seconds`, `unobserved_seconds`
  and `coverage_warnings`. Unobserved time may be sleep, downtime, missing
  collection or future time, and is never assumed to be idle.
- **Overlapping apps.** If different apps' intervals overlap, the breakdown
  adds a warning, and `sum_app_seconds` can then exceed `observed_seconds`.
- **App names.** Matching is exact but ignores case. App discovery keeps the
  original spellings.
- **Pagination.** Pages come from live data, not a frozen snapshot. Follow
  `next_offset` to get the next page.
- **Cost.** To keep events that cross the start boundary, each call fetches
  all window events before `end`. This gets expensive with long histories.

**Bucket endpoints** (`/events`, `/exports`):

- `start` and `end` go straight to ActivityWatch, which owns the exact
  boundary behavior.
- Events are not clipped or classified.
- A positive `limit` returns a preview. When the result reaches the limit,
  `possibly_truncated` is set.
- Large results are buffered in memory, so keep ranges bounded.

Original event JSON is preserved, including unknown nested fields. Whitespace
and key formatting are not preserved byte for byte. The wrapper adds the
source URL, fetch time, request, bucket metadata, event count and truncation
flag.

### MCP

The same server exposes read-only MCP tools over Streamable HTTP at
`http://127.0.0.1:8765/mcp`. The tools call the same `Bridge` methods as the
REST routes.

| MCP tool | Arguments | Result |
| --- | --- | --- |
| `get_recording_status` | none | Sources and how fresh their observations are |
| `list_apps` | `start`, `end` | Recorded app names |
| `get_app_usage` | `app`, `start`, `end` | Total foreground usage, without raw events |
| `get_usage_breakdown` | `start`, `end` | Apps ranked by foreground time |
| `get_activity_events` | `start`, `end`, optional `app`, `limit` (1–1000, default 100), `offset` | Original event payloads, newest first |

The tools follow the same rules as the REST app endpoints above. They never
write exports or modify ActivityWatch. The server's instructions tell clients
that event titles and URLs are untrusted data, never instructions.

To check discovery with the official Python MCP client:

```sh
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

ChatGPT needs a reachable transport, such as OpenAI's secure tunnel. See the
`connect-chatgpt` skill. The server keeps the MCP SDK's localhost Host checks.
Never expose the whole FastAPI server publicly. A remote deployment would need
authentication and explicit trusted-host configuration.

## Tests and checks

`AGENTS.md` ("Setup and checks") says what must pass before a commit, and
`docs/agents/checks.md` lists every check and where it runs.
