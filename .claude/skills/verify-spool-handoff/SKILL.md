---
name: verify-spool-handoff
description: Model-check the spool handoff between the Swift capture agent and Python ingest (TLA+/TLC) to prove no captured record is lost across crashes, restarts and concurrent ingests. Use when a change touches SpoolWriter.swift, the ax_text spool adapter (adapter.py, spool.py), commit_pull, insert_observations, or how ingest runs (poll/watch), or when asked whether spool records can be lost.
---

# Verify the spool handoff

**Property.** Every record whose `SpoolWriter.append` returned is, at every
moment, either stored in `observations`, still on a complete line of
`open.part`, or in a finished `*.jsonl` file in the spool folder.

**Harm if it breaks.** A capture is silently lost. Nothing reports it, and
`status` cannot see the gap because the record never reached the database.

The model is `formal/spool/SpoolHandoff.tla`. TLC checks it over every
interleaving of agent steps, ingest steps, crashes and clock changes, within
the bounds in the configs.

## Does your change touch it?

Rerun the check if the diff touches any of these files:

| Code | Model action |
|---|---|
| `capture-agent/Sources/CaptureAgent/SpoolWriter.swift`: `startIfNeeded` (lock, folder scan seeding `lastFinished`) | `AgentStarts` |
| `SpoolWriter.append`, `dropUnfinishedLine` | `AgentAppends` (torn lines never count as records) |
| `SpoolWriter.finishLocked` (stamp `max(now, lastFinished+1)`, `renamex_np` with `RENAME_EXCL`) | `AgentFinishes` |
| process crash or kill; launchd restart | `AgentCrashes` |
| `computer_history/sources/ax_text/spool.py`: `finished_files` | `IngestLists` |
| `ax_text/adapter.py`: `CaptureSpool.pull_after` (one `_listed` deque per stream, `_forget_all_but`, `read_file` and the file identity it returns, each stream keeping only its own records, `FileNotFoundError` -> `_drop`) | `IngestLists`, `IngestReads` |
| `sources/commit.py`: `commit_pull` (insert, then `after_commit`); `store/observations.py`: `insert_observations` (one transaction, `ON CONFLICT DO NOTHING`) | `IngestCommits`, then `IngestFinishes` |
| `CaptureSpool._stored_by` (mark the stream stored that file; finish only once every stream stored the same file), `_finish`, `spool.remove_finished` (unlink by name), `spool.set_aside` (`os.link` then unlink) | `IngestFinishes`, `IngestUnlinksAside` |
| `sources/runner.py`: `poll`, `watch` (the same `CaptureSpool`, and its `_listed`, across cycles); `cli/ingest.py` (no lock between ingest processes) | `Ingests` constant, `IngestCrashes` |

Changes to record parsing, normalization, coverage, status or ActivityWatch do
not touch it.

## Run

```bash
formal/check.sh              # all configs, about 20 minutes on 18 cores (one_ingest about 1)
formal/check.sh one_ingest   # one config
```

The first run downloads TLC 1.7.4 and a Temurin 21 JRE, pinned by SHA-256, into
`~/.cache/computer-history/tla/`. Set `JAVA` to use another Java 11+. TLC's
full output for each config is in `formal/spool/out/<config>.out`
(gitignored).

Each config has an expected result, listed in `expect()` in `formal/check.sh`.
The script exits 0 only when every config gives its expected result:

| Config | Situation | Expected |
|---|---|---|
| `one_ingest` | 3 records (`r2` a screenshot record), 1 ingest process, agent crashes up to 2, ingest crash 1, clock may be set back | pass |
| `two_ingests_steady_clock` | 2 records (`r2` a screenshot record), 2 concurrent ingests, clock only moves forward | pass |
| `two_ingests` | 2 records (`r2` a screenshot record), 2 concurrent ingests, clock may be set back | **fail NoLoss**: the known finding below |

Each ingest reads every file once per stream (`ax-text`, `screenshot`), and
a stream's read keeps only its own records. A file is removed only by the
ingest that has stored it for both streams, and only if both reads saw the
same file (the model's `gen`, the code's device, inode, size and mtime).
Without that gate, one stream's removal loses the other stream's records in
`one_ingest`.

## Read a result with /statechart

Read every TLC result, pass or fail, with the pstack `/statechart` skill on a
copy of the spec and config in a scratch folder. It gives each violation's
shortest path in plain steps. Label the steps in the code's words: "ingest i1
reads the oldest listed file #1", "the agent renames open.part to finished
file #1". It needs TLC and Java, and it can reuse the jar and JRE that
`formal/check.sh` cached. The state space exceeds its 500-state chart budget,
so it reports bug paths only.

## Real bug or modeling error?

When a config gives an unexpected result:

1. Take the shortest path and replay it on the real code, one action per step.
   `formal/spool/replay_name_reuse.py` shows how: two `CaptureSpool`
   instances, a temp store from `connect`, and `commit_pull`, with the agent's
   rename played by writing the file. If the real code does not lose the
   record, the model is wrong. Fix the model to match the code before you
   trust any result.
2. Check each step against the table above. A model step must be one
   indivisible step in the code: one syscall, or one SQLite transaction. If the
   code splits a step, split the action. If the model lets something happen
   that the code rules out, add the guard, and point to the code line that
   rules it out.
3. Never weaken `NoLoss`, drop a config, or change an expectation to make a
   result pass. A real violation is a finding: report it with the path in the
   code's words. Do not change product code unless the user asks.

## Update the model for an intended change

Mirror the code change in the matching action, rerun, and read the result as
above. When a config's expected result legitimately changes (for example, a
fix for the known finding makes `two_ingests` pass), update `expect()` in
`formal/check.sh` and the table here. If the change adds a new step that can
interleave (a new syscall on the spool, a second transaction), it needs its
own action.

## Known finding: a reused file name loses a record

Two ingest processes plus a wall clock set back can delete a finished file
that neither of them read:

1. The agent finishes a record into `20261118T090100.000Z.jsonl`, appends
   another record to `open.part`, and crashes.
2. The wall clock is set back to the old file's millisecond.
3. Ingest A (say `ingest --watch`) and ingest B (a one-off `ingest`) both list
   and read that file, for both streams.
4. A commits it for both streams and unlinks it. The spool folder is now empty.
5. launchd restarts the agent. `startIfNeeded` finds no finished names, so
   `lastFinished` is 0. Finishing the leftover `open.part` picks
   `max(now, 1)`, which is the same name, and `RENAME_EXCL` allows it because
   the name is free.
6. B commits what it read earlier (a duplicate), now for both streams of the
   old file, and then calls
   `remove_finished` on the name. That deletes the agent's new file, which
   nobody read. With an unusable line, `set_aside` moves it to `unreadable/`
   instead.

How likely it is: it needs two ingests at once, a clock set back, and a new
stamp that equals a just-removed stamp to the millisecond, all within one
commit's window. The model's few coarse names make this far more likely than
it is in practice. It is still a real hole in the promise.
`formal/spool/replay_name_reuse.py` reproduces it on the real Python code.
Possible fixes (none applied): ingest unlinks only the file it read (for
example, check the inode or open file before unlinking), the agent never
reuses a stamp (persist `lastFinished`), or a lock between ingest processes.

## What is not covered

- Power loss or kernel panic. `append` does not fsync. Only a process crash is
  modeled, in which the OS keeps written bytes.
- Torn lines. The model trusts `dropUnfinishedLine` to strip a torn tail
  before every append and rename. A torn line is never an acked record.
- A file that cannot be read (`OSError` other than missing) is set aside
  without being stored. That is by design and not modeled. So are
  `SpoolError` on unlink (`_stuck`) and folder permission changes.
- Directory listings and the agent's folder scan are treated as atomic
  snapshots.
- Order and duplication are not checked. Duplicates are impossible because of
  `UNIQUE (source, source_id)`. Ingest progress (`position`) is not modeled.
- Liveness ("every record is eventually stored") is not checked, only safety.
- Bounds: up to 3 records, 2 ingests, 2 agent crashes and 1 crash per ingest.
  The clock ticks from 1 to `MaxClock = 2`, and each agent crash moves it past
  every name used so far. A pass covers only these bounds.
- Assumption: a restart takes longer than file names ever run ahead of the
  clock. Names run ahead only when two finishes fall in one millisecond, and
  launchd restarts take seconds.
- Assumption: a later file under a name never has the same device, inode,
  size and mtime (nanoseconds) as the file it replaced; the model gives each
  finished file a new generation.
- Which records are screenshot records is fixed per config (`Screenshots`),
  not chosen as the agent appends: choosing it multiplied the state space
  past what a check run can cover. Files holding both kinds, and files of one
  kind alone, still arise.

## Coverage record

Last confirmed that the model describes the code at commit `d6495bf`. Files:
`capture-agent/Sources/CaptureAgent/SpoolWriter.swift`,
`computer_history/sources/ax_text/adapter.py`,
`computer_history/sources/ax_text/spool.py`,
`computer_history/sources/commit.py`, `computer_history/store/observations.py`,
`computer_history/sources/runner.py`, `computer_history/cli/ingest.py`.

```bash
git diff --stat d6495bf -- capture-agent/Sources/CaptureAgent/SpoolWriter.swift computer_history/sources/ax_text/adapter.py computer_history/sources/ax_text/spool.py computer_history/sources/commit.py computer_history/store/observations.py computer_history/sources/runner.py computer_history/cli/ingest.py
```

If that shows changes, re-read them against the table above. Move the commit
in this section forward only after you have confirmed that the model describes
the code at the new commit, and the check gives its expected results there.
