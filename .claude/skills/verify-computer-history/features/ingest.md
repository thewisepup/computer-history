# Ingest

`ingest` stores settled ActivityWatch events and the capture agent's finished
spool files in the database, one source line per stream; re-running it stores
nothing new, and `--watch` repeats it every 60 seconds.

## Sub-features

- `ingest-first` creates and migrates the database and stores every settled event.
- `ingest-held` holds back each still-growing ActivityWatch event until it settles.
- `ingest-idempotent` a second poll inserts 0 for data it already has.
- `ingest-spool` stores a finished spool file's records and deletes the file.
- `ingest-rejected` stores the usable lines of a file with a torn line and moves the file to `unreadable/`.
- `ingest-watch` the long-running collector logs one line per cycle.

## How to get to it (user POV)

- `computer-history ingest` for one poll.
- `computer-history ingest --watch` to keep polling until Ctrl-C.

## Driving it with chv

Preconditions:

- A fresh run; `$C doctor` all `ok`.

- **First poll.** Seed the spool and ingest. Run `$C spool-seed` then
  `$C cli ingest`. Exit `0`; stdout has `aw-afk inserted 4 ... held back 1`,
  `aw-web inserted 2 ... held back 0`, `aw-window inserted 17 ... held back 1`,
  `ax-text inserted 9`, `screenshot inserted 5`.
- **Stored rows.** Run `$C sql "SELECT source, COUNT(*) n FROM observations GROUP BY source"`.
  Counts match the inserted numbers (4, 2, 17, 9, 5).
- **Spool emptied.** Run `$C spool-ls`. No `*.jsonl` file remains.
- **Second poll.** Run `$C cli ingest` again. Every stream reports
  `inserted 0`; `held back 1` stays on `aw-afk` and `aw-window`.
- **Held event settles.** Run `$C aw-advance` then `$C cli ingest`.
  `aw-afk inserted 1` and `aw-window inserted 1` (the formerly growing events),
  each `held back 1` (the new ones).
- **Rejected line.** Run `$C spool-seed --bad` then `$C cli ingest`. Exit `0`;
  the file's two good lines are fixture records already stored, so stdout reads
  `ax-text ... skipped 1` and `screenshot ... skipped 1`; stderr has
  `WARNING sources.capture_spool.adapter  spool file set aside  file=... target=.../spool/unreadable/...`
  with `error="it has 1 unusable line(s), 1 of no readable kind (its usable lines are stored)"`.
  Then `$C spool-ls` shows the file under `unreadable/`.
- **Watch.** Run `$C watch-start` (it returns once the first cycle is logged),
  `$C doctor` (the watch pid line is `ok`), `$C cli status` (`Ingest:` reads
  `ok, last cycle ...` and the checks `backend  ok: recording, last seen ...`),
  then `$C watch-stop`. The `NN-watch.txt` transcript has
  `INFO    cli.ingest  watching (Ctrl-C to stop)  ... interval_s=60` and one line
  `INFO    sources.cycle_report  cycle ok: aw-afk +0 (1 dup, 1 held); ...; screenshot +0 (0 dup, 0 held)`.

## Gotchas

- The fixture records in `spool-seed` share fixed ids; seeding them twice
  stores them once (`skipped` on ax-text), which is correct, not a failure.
- The fixed-id records are 2026-11-18; they do not make the agent `alive`.
  Use `$C spool-seed --now` for that.
- `aw-window` reports `skipped 3` on repeat polls: the resume reads 10 minutes
  back and re-sees stored events. Assert `inserted 0`, not `skipped 0`.
- Stdout pads its counts (`inserted      4  skipped      0  held back   1`);
  match the words and numbers, not the spacing.
- `rejected` counts only well-formed records of the stream's kinds with a bad
  field; a torn line has no readable kind, so `--bad` sets the file aside
  without a `rejected` count.
- The `unreadable/` folder is created `drwxr-xr-x` while the spool itself is
  `drwx------` (seen 2026-11-19); the files inside are `0600`.
- `--watch` sleeps 60s between cycles; one cycle is all a short run captures.
  A separate shell `sleep` between drives can stall for minutes (seen
  2026-11-27: background processes advanced only while a command ran), so wait
  inside one command, as `watch-start` does, never across calls.
  Stop it with `$C watch-stop`, never by process name: the live LaunchAgent
  runs the same command.
