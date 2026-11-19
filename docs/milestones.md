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

- [ ] Swift CLI builds to a stable path, signed and started by its own
      LaunchAgent; Accessibility permission granted and surviving a rebuild
      and a restart.
- [ ] Captures on app/window/title switch + 30s heartbeat; silent when
      locked or idle (native idle detection).
- [ ] Content-role text only, 50 KB cap with cut-offs recorded, full text +
      hash on every capture, `kAXSecureTextField` always skipped.
- [ ] Denylisted apps and pause/resume leave labelled records, no text.
- [ ] Per-call timeout verified: a hung app costs one capture, not the agent.
- [ ] Finished-file JSONL spool (one-minute files); backend adapter ingests
      finished files into observations + signals, then deletes them.
- [ ] `status` reports the agent: last capture, liveness, spool backlog.
- [ ] Kill the backend for a day → spool accumulates, catch-up ingests all.

### M3 — Capture agent: screenshots + OCR

- [ ] ScreenCaptureKit capture at the decided scope, downscaled JPEG.
- [ ] Perceptual-hash dedup drops near-identical frames (verify on a static
      screen).
- [ ] Vision OCR runs in the agent; OCR text in the spool record; image path
      in `extras`.
- [ ] Only text ever crosses into Python; JPEGs stay on disk.
- [ ] A normal day lands within the storage budget; disk usage queryable.

### M4 — Login agents + reliability

- [ ] LaunchAgent for the backend (the capture agent's arrives in M2); both
      start at login.
- [ ] Reboot test: recording resumes with no manual steps.
- [ ] Sleep test: ingest progress advances across wake; the gap is ingested, and real
      coverage gaps are reported as warnings, never guessed.
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
