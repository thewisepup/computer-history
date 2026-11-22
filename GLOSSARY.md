# Computer History

A local activity layer that records what happens on the computer and attributes it to projects and types of work, so any AI assistant can ask where time went.

## Language

### Capture and ingest

**Source**:
A system outside the backend that reports activity: ActivityWatch or the capture agent.
_Avoid_: Provider, integration, watcher

**Stream**:
One kind of activity a source reports, such as focused windows, AFK state, browser tabs, window text or screenshots.
_Avoid_: Bucket, feed, source (for this meaning)

**Capture agent**:
The program on the Mac that reads the focused window's text and takes its screenshot, leaving what it read in the spool. It observes and writes; it never interprets.
_Avoid_: Recorder, daemon, tracker

**Capture**:
One reading of the focused window at a single instant, taken by the capture agent. It has no duration.
_Avoid_: Snapshot, sample, event

**Window text**:
The text the capture agent reads from the focused window through Accessibility.
_Avoid_: AX text, content

**Screenshot**:
An image of the focused window taken by the capture agent. It never leaves the Mac.
_Avoid_: Frame, screen grab, snapshot

**Screenshot record**:
The spool record that says what became of a capture's screenshot: kept, a duplicate of one kept earlier, or not taken and why, with its recognized text.
_Avoid_: Frame record, image event

**Recognized text**:
The text read out of a screenshot by on-device text recognition.
_Avoid_: OCR text, image text

**Spool record**:
One entry the capture agent leaves in the spool: a capture, a screenshot record, an exclusion, a pause, a resume, a sleep or a wake.
_Avoid_: Event, entry, line

**Exclusion**:
A spool record saying a denylisted app was in front, carrying no text.
_Avoid_: Skip, redaction

**Pause**:
A spool record marking that the user stopped capture on purpose; a **Resume** marks it starting again.
_Avoid_: Stop, mute

**Sleep**:
A spool record (`slept`) marking that the Mac went to sleep; a **Wake** (`woke`) marks it waking. Neither carries an app, a window or text.
_Avoid_: Suspend, standby, lid closed

**Spool**:
The folder where the capture agent leaves captures for the backend to collect. Anything in it has not yet been stored.
_Avoid_: Queue, buffer, inbox

**Live folder**:
`~/Library/Application Support/ComputerHistory/`, holding the real database, spool and screenshots the capture agent and the stable install use.
_Avoid_: Prod folder, real folder

**Stable install**:
The copy of the code in a marked version folder under the live folder's `versions/`; the only code whose profile is stable. `install` builds it from a commit that passed the release gate, and `current` points at the version in use.
_Avoid_: Release, production build

**Update**:
Moving the stable install's `current` forward to the newest commit the release gate passes, after a pre-update backup, kept only once the backend completes an ok cycle on it under the spool hold.
_Avoid_: Upgrade, deploy, release

**Fallback**:
What an update does on its own when the new version's backend crashes, fails its first cycle for a reason other than an unavailable source, completes none in time, or the wait is interrupted: the old version back as `current`, the pre-update backup restored only when the schema changed.
_Avoid_: Revert, auto-rollback

**Rollback**:
Switching `current` to the previous version by hand, keeping the version left as previous; no network and no backup restored. It is refused when the database's schema is newer than the previous version can open, until its pre-update backup is restored.
_Avoid_: Downgrade, revert

**Installed agent**:
The capture agent app at its one fixed path, `~/Applications/ComputerHistoryAgent.app`, and `installed-agent.json` in the live folder naming the commit it was built from. Every version folder carries a copy of an agent app with the commit it came from; none is ever registered from there. With no record the installed agent is unknown, update counts it as changed, and `status` says `built from unknown`.
_Avoid_: Deployed agent, agent version

**Agent swap**:
Update installing a changed capture agent's app from the new version folder over the fixed path, after the backend's first ok cycle, then waiting for a record captured since. A record verifies it; no record during 120 active seconds, or an agent that never starts, is an **agent fallback**: the old version's app goes back over the fixed path while the new backend stays, and the build that fell back is kept aside in the new version folder as `ComputerHistoryAgent.fell-back.app`. When the installed app can't be kept in the old version folder or the installed agent can't be unregistered, the agent is **not swapped** and keeps running.
_Avoid_: Agent deploy, agent rollback (rollback is the command)

**Update log**:
`update-log.jsonl` in the live folder, one line per update, fallback, agent fallback, rollback and agent moved by rollback; an `updated` line carries the capture agent's outcome, and `status` shows the last one that moved `current` and whose action it knows, and the last agent fallback until a later update installs or keeps an agent or a rollback moves it.
_Avoid_: Changelog, audit log

**Spool hold**:
`spool-deletion-held` beside the database, placed by an update: while it exists ingest stores spool files but deletes none, and the backend's first ok cycle removes it.
_Avoid_: Lock, freeze, pin

**Profile**:
Stable or dev, decided from where the running code lives. Dev is everything that is not the stable install; it uses `ComputerHistory-dev/` and is refused the live folder.
_Avoid_: Mode, environment

**Release gate**:
The named CI checks a `main` commit must all have passed on its push run before the stable install may hold it.
_Avoid_: Required checks, green build

**Agent install guard**:
The check the capture agent's install script runs before building: the checkout must be on `main`, clean, at `origin/main`, with the release gate's capture-agent checks passed, and the stable install at that commit or newer. `--force` skips it.
_Avoid_: Preflight, safety check

**Host adapter**:
The one seam to macOS and the network (launchctl, GitHub, reading a checkout's git state, building with uv, building and installing the capture agent, checking and opening ActivityWatch's app, posting a notification), live on the Mac and a fake in tests. Every notification goes through it, under one title, and `COMPUTER_HISTORY_NOTIFY=0` turns them off.
_Avoid_: System client, platform layer

**Daily backup**:
The copy of the database the backup LaunchAgent takes once a day (or after wake, when the day's run was missed) into `backups/daily/`, checked with SQLite's integrity check; the newest seven are kept.
_Avoid_: Snapshot, dump, archive

**Pre-update backup**:
The copy of the database an update takes before it switches versions, kept in `backups/pre-update/` apart from the dailies and named for the version that was current; a fallback restores it when the schema changed.
_Avoid_: Checkpoint, safety copy

**Restore**:
Putting a backup in the database's place, the current database set aside (never deleted); for the live database the backend, the watchdog and the daily backup are stopped around it.
_Avoid_: Revert, recover, rollback (for this meaning)

**Watchdog**:
The stable install's every-minute check that the capture agent, ActivityWatch and the backend are recording, which notifies Brandon of a problem and reopens ActivityWatch when it is down. It calls the backend a problem only when it has gone silent; failing cycles are the failure streak's to report.
_Avoid_: Monitor, health check, supervisor

**Finding**:
What one watchdog run, or `status` by the same rules, concluded about one subject: its verdict, the reason, and when the subject was last seen working.
_Avoid_: Result, alert, status

**Verdict**:
A finding's conclusion: ok (clears a notified problem), problem (notifies, at most once an hour), or cannot tell (neither).
_Avoid_: Health, state, level

**Threshold**:
How long a watchdog subject may stay silent before its silence is a problem, set per subject in the agent's config file.
_Avoid_: Timeout, limit, baseline

**Dev snapshot**:
A copy of the live database taken into dev's database by `dev snapshot`, read-only and while the stable backend keeps writing; the one read of live data dev is allowed. It never includes the spool or screenshots.
_Avoid_: Dump, export, clone

**Event**:
A stretch of activity with a start and an end, as reported by ActivityWatch.
_Avoid_: Capture

**Settled**:
Said of activity that its source will no longer change, so it can be stored.
_Avoid_: Closed, final, complete

**Observation**:
One piece of activity exactly as its source reported it. Never changed once stored.
_Avoid_: Raw event, log entry, record

**Signal**:
The cleaned, uniform reading of an observation's content. Can always be thrown away and rebuilt from observations.
_Avoid_: Feature, normalized event

**Ingest**:
Moving settled activity from a source into stored observations and signals.
_Avoid_: Import, sync

**Backfill**:
A one-time ingest of history that existed before this install was set up.
_Avoid_: Import, catch-up

**Progress**:
How far ingest has stored a stream, and up to when that stream is complete.
_Avoid_: Cursor, watermark, offset, checkpoint

**Ingest health**:
`ingest-health.json` beside the database, which `ingest --watch` rewrites after every cycle: when the last cycle ran, whether it succeeded and why not (and whether every failure was an unavailable source), when one last succeeded, and the failure streak. The watchdog, update's first-cycle wait and `status` all read it. It says nothing about coverage.
_Avoid_: Uptime, backend heartbeat, watch heartbeat (the capture agent's heartbeat is its own record)

**Failure streak**:
The run of watch-loop cycles that failed in a row. It notifies once it reaches five cycles, at most hourly while it lasts, and once when an ok cycle ends it; it never names the error.
_Avoid_: Outage, incident, error count

### Coverage and time

**Coverage**:
Which stretches of time a source actually observed.
_Avoid_: Uptime, health

**Unobserved**:
A stretch no source can account for. Never assumed to be idle or away.
_Avoid_: Idle, gap, missing, empty

**Explained gap**:
A stretch without text that a spool record accounts for, through an exclusion, a pause or a sleep.
_Avoid_: Unobserved (for this meaning)

**AFK**:
ActivityWatch's verdict that the user is away from the keyboard. A state that splits and gates activity, never content itself.
_Avoid_: Away, inactive

**Idle**:
The capture agent's own judgment, from macOS input time, that nobody is using the Mac, during which it captures nothing.
_Avoid_: AFK (for this meaning)

**Foreground time**:
Time some window or tab was in front, whether or not the user was there.
_Avoid_: Screen time, active time

**Attended time**:
Foreground time when the user was not AFK.
_Avoid_: Active time, engaged time

### Attribution

**Project**:
An outcome time goes toward, never a kind of activity. The AI may propose one; the user confirms, renames, merges or archives it.
_Avoid_: Category, activity, client, workstream

**Proposed project**:
A project the AI named that the user has not yet confirmed. Proposed projects are the approval queue.
_Avoid_: Draft, suggested project

**Merge**:
Folding one project into another so its name forever resolves to the survivor.
_Avoid_: Combine, dedupe

**Work type**:
The kind of labor being done, from a closed vocabulary only the user owns. The AI selects one and never invents one.
_Avoid_: Category, activity type, task type

**Tag**:
A free-form label the AI attaches to a block for search. Never counted in time totals.
_Avoid_: Label, keyword

**Classification window**:
A fixed five-minute slice of time the classifier labels as one unit.
_Avoid_: Window (that word means an app window), bucket, slot

**Digest**:
The summary of one classification window's signals that the classifier reads.
_Avoid_: Context, prompt

**Block**:
A continuous stretch of time carrying exactly one project and one work type.
_Avoid_: Session, segment, entry, span

**Unassigned**:
A block with no project, because the classifier was not confident enough.
_Avoid_: Unknown, uncategorized, other

**Evidence**:
The signals that overlap a block's time, shown as the reason for its labels.
_Avoid_: Sources, proof

**Correction**:
A user's setting of a block's project, work type or tags. A corrected block is locked: the classifier never changes it again.
_Avoid_: Override, edit, fix

**Split**:
Cutting one block into two at a point in time; the only way a user changes a block's time.
_Avoid_: Trim, resize

**Re-label**:
The classifier labelling again the uncorrected blocks of the last two weeks after the user changes the project set.
_Avoid_: Reclassify, refresh

**Bootstrap re-label**:
The one-time re-label of every uncorrected block when the user adds their first work type.
_Avoid_: Backfill

### Review

**Weekly review**:
A frozen account of one Monday-to-Sunday week: totals, bottlenecks and a narrative. A new one never replaces an earlier one.
_Avoid_: Report, digest, summary

**Bottleneck**:
A project and work type pair ranked by how much time it took across the week.
_Avoid_: Hotspot, time sink

**Shortlist**:
The bottlenecks big enough to clear the materiality floor, from which suggestions are picked.
_Avoid_: Top N, candidates

**Materiality floor**:
The minimum size a bottleneck must reach to be considered for a suggestion.
_Avoid_: Threshold, cutoff

**Suggestion**:
One concrete automation proposed in a weekly review, with its evidence, the workflow to judge and a ready-to-run prompt.
_Avoid_: Recommendation, idea, tip

**Nudge**:
The reminder, shown in status and reviews, that no work types exist yet. It is the whole of onboarding.
_Avoid_: Onboarding prompt, wizard

### Synthetic datasets

**Synthetic dataset**:
A database of invented history built through the real ingest path, with its manifest. A persona, a scenario, a scale tier with its heavy factor, and a seed pick it, and the same four always give the same contents.
_Avoid_: Fixture, fake data, mock database

**Persona**:
Who a synthetic user is, as typed config: apps, sites, projects, daily rhythm and switch rate. It never decides what goes wrong.
_Avoid_: Profile, user type

**Scenario**:
What happens over a dataset's range: faults, extra sleeps and long AFK spans placed on the persona's ordinary timeline. It never changes who the user is.
_Avoid_: Case, story

**Scale tier**:
How many days a dataset covers: day, week, month or year.
_Avoid_: Size, scale

**Heavy**:
A factor that makes a persona a heavier user: faster switching, more text and weekends worked. The workday keeps its length.
_Avoid_: Stress mode, load

**Timeline**:
The source-neutral account of a dataset's range: stretches covering it end to end, plus the faults over them. Every renderer reads the same one.
_Avoid_: Schedule, script, event list

**Stretch**:
One span of a synthetic timeline: an app and window in front with the user present or AFK, or the Mac asleep. Elsewhere, stretch is a plain word for any span of time.
_Avoid_: Segment, block (that word means a labelled span), event

**Fault**:
A span of a timeline in which sources fail: ActivityWatch down, the capture agent down, Accessibility permission lost, capture paused or an app excluded.
_Avoid_: Outage (that is one kind), error, incident

**Renderer**:
Turns a whole timeline into one source family's raw data, the way that source really records it, and names the streams it feeds.
_Avoid_: Exporter, writer

**Manifest**:
The true answers for a dataset, computed from its timeline and never its database: time per app and domain, AFK, unobserved time, explained gaps and counts.
_Avoid_: Snapshot, golden file, expected output

**Cost counter**:
One deterministic measure of the SQLite work an operation does: statements run, VM steps, full scans or database pages.
_Avoid_: Metric, timing, benchmark

**Baseline**:
The committed cost counters per operation and dataset that the performance gate compares against. It changes only on purpose, with the reason in the pull request.
_Avoid_: Budget, threshold
