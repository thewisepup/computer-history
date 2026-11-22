# Rebuild signals

`rebuild-signals` wipes the derived `signals` table and re-projects every
stored observation through its source's projector, aborting and rolling back
when the result would shrink suspiciously.

## Sub-features

- `rebuild-same` a rebuild with unchanged projectors keeps the same count.
- `rebuild-missing` a missing database is refused, not created.
- `rebuild-observations-untouched` raw observations are never changed.

## How to get to it (user POV)

- `computer-history rebuild-signals`
- `computer-history rebuild-signals --allow-shrink`

## Driving it with chv

Preconditions:

- A fresh run; `$C doctor` all `ok`.

- **Missing database.** Run `$C cli rebuild-signals`. Exit `1`, stderr
  `no database at ...; run \`computer-history ingest\` first`, no traceback;
  `$C cli status` still reads `not created yet`.
- **Populate.** Run `$C spool-seed` and `$C cli ingest`.
- **Before.** Run `$C sql "SELECT COUNT(*) FROM signals"` and
  `$C sql "SELECT COUNT(*), SUM(LENGTH(payload)) FROM observations"`.
- **Rebuild.** Run `$C cli rebuild-signals`. Exit `0`; `signals before` equals
  `signals after`, `skipped 0 (malformed payloads)`.
- **After.** Repeat both `sql` queries. Signals count unchanged; observations
  count and payload length identical to Before.

## Gotchas

- Signals cover captures, slept and woke records only for ax-text (excluded,
  paused and resumed records project to nothing), so signals < observations is
  expected.
- The shrink guard only fires after a projector change; the seed cannot
  trigger it. Reaching `--allow-shrink` needs a code change and is out of
  this map's reach.
