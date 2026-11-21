# Milestones

Section references (§3, §8.1) point into [DESIGN.md](DESIGN.md).

**Ordering principle: all ingestion before any intelligence.** The classifier
is built once against the full signal set; weeks of data accumulate as an
eval corpus; the scariest risk (TCC under LaunchAgents) is exercised first.
Accepted cost: the aha moment arrives at M5. The POC serves AI clients until
M6 replaces it.

### M1 — Package + store + AW ingest ✅ (2026-11-17)

- [x] Package skeleton (`store/`, `sources/`, `cli.py`) with tests running.
- [x] Schema created on first run: all §3 tables + the `block_evidence_v` view.
- [x] AW adapter polls window / AFK / Chrome buckets (settled events only) and
      writes observations + signals in one transaction.
- [x] AW data visibly normalized: `app`, `domain`, `url`, `title` populated in
      `signals`; payloads verbatim in `observations`.
- [x] Re-running ingest over the same range adds zero rows (idempotency test).
- [x] `status` CLI: per-source cursor freshness + coverage gaps.
- [x] `rebuild-signals` wipes and re-projects; result identical (test).
- [x] One-time `backfill` ingests Brandon's existing AW history.

### M2 — Capture agent: AX text

Remaining before ✅: a full restart of the Mac and real sizes after a day of
use ([#12](https://github.com/thewisepup/computer-history/issues/12)).

- [ ] Swift CLI builds to a stable path, signed and started by its own
      LaunchAgent; Accessibility permission granted and surviving a rebuild
      and a restart. *(Rebuilds and a logout/login verified 2026-11-18; a
      full restart is not.)*
- [x] Captures on app/window/title switch + 30s heartbeat; silent when
      locked or idle (native idle detection).
- [x] Content-role text only, 50 KB cap with cut-offs recorded, full text +
      hash on every capture, `kAXSecureTextField` always skipped.
- [x] Denylisted apps and pause/resume leave labelled records, no text.
- [x] Per-call timeout verified: a hung app costs one capture, not the agent.
- [x] Finished-file JSONL spool (one-minute files); backend adapter ingests
      finished files into observations + signals, then deletes them.
- [x] `status` reports the agent: last capture, liveness, spool backlog.
- [x] Kill the backend for a day → spool accumulates, catch-up ingests all.
      *(17 hours on 2026-11-18/19, a small backlog since the Mac was mostly
      locked; a full day's backlog is covered by the automated test and the
      TLA+ model in `formal/`.)*

### M3 — Capture agent: screenshots + text recognition

Remaining before ✅: the measurements on real screens
([#38](https://github.com/thewisepup/computer-history/issues/38)), the
Screen Recording unknowns
([#39](https://github.com/thewisepup/computer-history/issues/39)), a normal
day within the storage budget, and a static screen saving at most one image
per keep-after limit while its text is read. All on Brandon's Mac.

- [ ] ScreenCaptureKit still of the focused window only, downscaled JPEG in
      dated folders beside the database. *(Saving, downscaling and folders
      are checked through the scripted Mac; the live ScreenCaptureKit call
      and its window matching wait for #38.)*
- [ ] Thumbnail dedup drops near-identical screenshots per window, with a
      keep-after limit. *(The rule is tested on rendered pages and in the
      end-to-end check; a static screen saving at most one image per
      keep-after limit, and the thresholds on real screens, wait for #38.)*
- [x] Vision text recognition runs in the agent, off the capture thread;
      recognized text in the screenshot record; image path in `extras`.
      *(Vision is tested on a fixture image; legibility and timing on real
      screens wait for #38.)*
- [x] Every capture gets one screenshot record (`kept`, `duplicate`,
      `secure-field`, `no-permission` or `failed`); a duplicate points at its
      kept image and copies its text.
- [x] Only text ever crosses into Python; JPEGs stay on disk. *(The
      end-to-end check runs ingest, `status` and `rebuild-signals` with the
      screenshots folder closed to them.)*
- [x] `status` reports screenshots: last kept, counts by status, disk use in
      total and today, and a warning when the grant is missing.
- [ ] A missing Screen Recording grant posts one reminder a day that opens
      the settings pane; the grant survives a rebuild. *(The once-a-day rule
      is tested; posting and clicking from the windowless agent, the settings
      link on macOS 26, `install.sh`'s request and the grant across rebuilds
      wait for #39.)*
- [ ] A normal day lands within the storage budget (150 MB, provisional).

### M4 — Login agents + reliability

- [ ] LaunchAgent for the backend (the capture agent's arrives in M2); both
      start at login.
- [ ] Reboot test: recording resumes with no manual steps.
- [ ] Sleep test: ingest progress advances across wake; the gap is ingested, and real
      coverage gaps are reported as warnings, never guessed.
- [x] A daily backup of the database, seven kept and each integrity-checked,
      and `restore` putting one back with the current database set aside.
      *(The LaunchAgent running a missed backup after wake waits for the Mac
      verification, #110.)*
- [ ] From here, data accumulates unattended (the eval corpus for M5).

### M5 — Classification

- [ ] 5-minute windowing with digests from `signals`; fully-AFK windows
      skipped (no LLM call).
- [ ] OpenRouter client, one hard-coded model, batched windows, strict JSON
      schema validation on output.
- [ ] Projects: new names create `proposed` rows; archived names resolve via
      merge forwarding.
- [ ] Work types: selected from active list only; unknown value rejected →
      NULL; confidence < threshold → NULL project.
- [ ] Block assembly: merge same-label windows, split at >5-min AFK gaps.
- [ ] Corrected-block guard in every write statement (race test: correct a
      block mid-run, verify it survives).
- [ ] Hourly scheduler + 14-day horizon; `classification_runs` recorded;
      `classify-backfill` command for older data.
- [ ] A day of multi-source activity → labelled blocks within an hour;
      re-running the same range changes nothing.

### M6 — MCP + corrections

- [ ] All §8.1 read and write tools live on `/mcp`; REST mirrors under `/api`.
- [ ] From Claude (direct) **and** ChatGPT (tunnel): "anything I need to
      approve?" answered via `list_projects(status='proposed')` + work-type
      nudge.
- [ ] Correct, split, confirm/rename/merge/add projects, and manage work
      types — all from an AI client.
- [ ] Bootstrap re-label fires on the first work-type approval; 14-day
      re-label fires on project changes; corrections survive both (test).
- [ ] Swagger `/docs` usable as the admin tool for every route.
- [ ] POC (`history.py` / `history_mcp.py`) deleted.

### M7 — Weekly review

- [ ] Stage-1 deterministic scoring + materiality-floor shortlist.
- [ ] Stage-2 LLM selection: 1–3 suggestions with evidence / workflow /
      runnable; no candidates outside the shortlist.
- [ ] Scheduled Monday generation + `generate_review_now`; both run
      classification catch-up first.
- [ ] Empty week stores a "no classified work" review; empty `work_types`
      stores the nudge.
- [ ] The same stored review is returned by Claude, ChatGPT, and REST.

### M8 — React UI

- [ ] Built to static files, served at `/`.
- [ ] Timeline, breakdowns, project + work-type management, correct/split,
      review + suggestions, recording status + disk usage, screenshot display.
- [ ] Parity check: every MCP write action is doable in the browser.

### M9 — Early adopters

- [ ] Setup docs + rough install script.
- [ ] A technical friend's Mac runs the full pipeline end to end.
