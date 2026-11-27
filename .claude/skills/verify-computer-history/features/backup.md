# Backup and restore

`backup` takes today's daily backup of the database into `backups/daily/`
beside it, at most one a day, checked with SQLite's integrity check;
`restore` puts a day's backup (or a backup file) in the database's place and
sets the replaced database aside, never deleting it.

## Sub-features

- `backup-take` the first backup of the day copies the database and reports its schema, size and integrity.
- `backup-again` a second backup the same day takes nothing.
- `backup-status` `status`'s `Backups:` section shows the latest and how many are kept.
- `restore-day` restoring a day's backup sets the current database aside.
- `restore-missing` a day with no backup is refused and nothing changes.

## How to get to it (user POV)

- `computer-history backup`
- `computer-history restore <YYYY-MM-DD | backup file>`

## Driving it with chv

Preconditions:

- A run with a database (`$C spool-seed` and `$C cli ingest`); `$C doctor` all `ok`.

- **Take.** Run `$C cli backup`. Exit `0`; stdout has `Backed up <run db>`,
  `copied to <run folder>/backups/daily/history-<today>.db` and
  `schema v5, ... KB, integrity ok`.
- **Again.** Run `$C cli backup`. `Today's backup is already taken: <path>`.
- **Status.** Run `$C cli status`. `Backups:` has `latest        <today>, taken ...`,
  `daily         1 kept (the newest 7), oldest <today>`,
  `integrity     each passed SQLite's integrity check before it was kept` and
  `folder        <run folder>/backups`.
- **Restore.** Run `$C cli restore $(date +%Y-%m-%d)`. Exit `0`;
  `Restored the daily backup of <today> into <run db>`, a `from` line and
  `set aside     <run folder>/backups/set-aside/history-<stamp>.db (never deleted)`.
  Then `$C sql "SELECT COUNT(*) FROM observations"` matches the count at backup time.
- **Missing day.** Run `$C cli restore 2001-01-01`. Exit `1`, stderr
  `restore failed: no daily backup of 2001-01-01; the kept ones are <today> (nothing was changed)`.

## Gotchas

- `backup` on a missing database prints `No database at ... yet: nothing to back up`.
- `restore` stops and restarts the stable LaunchAgents only when its target is
  the live database; on a run's database it touches no agent, so no
  `stopped, then started again` lines appear.
- The backups live in the run's state folder, so `$C down` deletes them.
