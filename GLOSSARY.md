# Computer History

A local activity layer that records what happens on the computer and attributes it to projects and types of work, so any AI assistant can ask where time went.

## Language

### Capture and ingest

**Source**:
A system outside the backend that reports activity: ActivityWatch or the capture agent.
_Avoid_: Provider, integration, watcher

**Stream**:
One kind of activity a source reports, such as focused windows, AFK state, browser tabs or window text.
_Avoid_: Bucket, feed, source (for this meaning)

**Capture agent**:
The program on the Mac that reads the focused window's text and leaves it in the spool. It observes and writes; it never interprets.
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

**Recognized text**:
The text read out of a screenshot by on-device text recognition.
_Avoid_: OCR text, image text

**Spool record**:
One entry the capture agent leaves in the spool: a capture, an exclusion, a pause or a resume.
_Avoid_: Event, entry, line

**Exclusion**:
A spool record saying a denylisted app was in front, carrying no text.
_Avoid_: Skip, redaction

**Pause**:
A spool record marking that the user stopped capture on purpose; a **Resume** marks it starting again.
_Avoid_: Stop, mute

**Spool**:
The folder where the capture agent leaves captures for the backend to collect. Anything in it has not yet been stored.
_Avoid_: Queue, buffer, inbox

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

### Coverage and time

**Coverage**:
Which stretches of time a source actually observed.
_Avoid_: Uptime, health

**Unobserved**:
A stretch no source can account for. Never assumed to be idle or away.
_Avoid_: Idle, gap, missing, empty

**Explained gap**:
A stretch without text that a spool record accounts for, through an exclusion or a pause.
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
