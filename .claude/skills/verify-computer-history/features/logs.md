# Logs

`logs` prints the JSON log's records as text, filtered by time, level, run or
logger; every command writes that log, so it answers "what did ingest just do".

## Sub-features

- `logs-filter` `--since`, `--level`, `--run` and `--logger` narrow the records.
- `logs-json` `--json` prints the raw JSON lines.

## How to get to it (user POV)

- `computer-history logs --since 1h --level warning`
- `computer-history logs --json`

## Driving it with chv

Preconditions:

- A run that has logged something worth finding: the Rejected line step in
  [ingest](./ingest.md); `$C doctor` all `ok`.

- **Filter.** Run `$C cli logs --since 1h --level warning`. Exit `0`; the
  records go to stderr, among them
  `WARNING sources.capture_spool.adapter [ingest <run id>]  spool file set aside  file=...`.
- **JSON.** Run `$C cli logs --since 1h --json`. One JSON object per line.

## Gotchas

- `chv` points `COMPUTER_HISTORY_LOG_DIR` at the run's evidence `logs/`, so
  this reads only the run's own log, never the live one.
- `logs` writes its records to stderr, not stdout; the transcript keeps both.
