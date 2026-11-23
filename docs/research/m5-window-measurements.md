# Classification windows and digest size on real data

Measured 2026-11-22 on a `dev snapshot` of Brandon's live database, read-only,
with `docs/research/measure_windows.py` (plus two ad-hoc checks below). Days are
local (America/Los_Angeles). Answers #154.

## What the snapshot holds

| Source | Rows | From |
|---|---|---|
| `aw-window` | 8,068 | 2026-11-12 |
| `aw-web` | 5,249 | 2026-11-12 |
| `aw-afk` | 175 | 2026-11-12 |
| `ax-text` | 3,159 | 2026-11-20 |
| `screenshot` | 515 | 2026-11-22 (about 6 hours) |

So only 2.5 days have window text and 6 hours have screenshot text. The text
numbers are a first read, not a week's average.

## Windows per day

A window is **active** when `aw-afk` reports any not-AFK time in it,
**fully AFK** when it reports only AFK time, and **no AFK data** when it has
signals but `aw-afk` says nothing about it.

| Day | Active | Fully AFK | No AFK data (with signals) |
|---|---|---|---|
| 11-12 (partial) | 24 | 78 | 0 |
| 11-13 | 32 | 256 | 0 |
| 11-14 (Sat) | 0 | 288 | 0 |
| 11-15 (Sun) | 0 | 288 | 0 |
| 11-16 | 71 | 217 | 0 |
| 11-17 | 88 | 200 | 0 |
| 11-18 | 58 | 136 | 64 |
| 11-19 | 81 | 89 | 118 |
| 11-20 | 98 | 178 | 12 |
| 11-21 (Sat) | 6 | 177 | 58 |
| 11-22 (Sun, partial) | 29 | 161 | 6 |

- Workdays run **58 to 98 active windows** (5 to 8 hours).
- Up to **118 windows a day have signals but no AFK verdict** (11-19). That's
  a third case beside active and fully AFK, which DESIGN §5 doesn't address.
  It may be the AFK-after-sleep bug (#41) or an ActivityWatch gap. If they're
  classified, a day reaches about **200 windows**.

## Text per active window

Characters of `title` + `url` + `text` across every signal overlapping the
window. Tokens are approximated as characters / 4.

| Sample | Windows | Raw p50 / p90 | Exact-text dedup p50 / p90 | ≈ tokens p50 / p90 |
|---|---|---|---|---|
| All days (mostly titles and URLs) | 487 | 1.9K / 125K | 0.8K / 86K | 190 / 21K |
| Since `ax-text` started | 148 | 103K / 182K | 68K / 134K | 17K / 34K |
| Since screenshots started | 20 | 166K / 240K | 86K / 167K | 21K / 42K |

Per window, since `ax-text` started: about 15 `aw-window`, 3 `aw-web` and 17
`ax-text` signals at p50 (p90: 39, 27, 31). With screenshots on, 17 screenshot
signals too. Distinct apps p50 3 (p90 6), domains 1 (3), titles 12 (24).

### How much is repetition

The same document is captured every 30 seconds with small changes, so exact
de-duplication barely helps:

- **Exact text:** 68K → 68K characters p50. Each capture differs slightly.
- **Lines:** no help. AX text arrives as one line (median 0 newlines per
  signal).
- **Novel 8-word shingles** (count a word only if the 8 words starting at it
  haven't appeared earlier in the window): **35K characters p50, 75K p90,
  about 8.6K / 19K tokens.** Half the text is repeated content.

Most text comes from two apps (a coding-agent client and the browser), about
70% of all `ax-text` characters.

## What this means for the open tickets

- **Digest (#157):** even after near-duplicate removal, a window's text is
  about 8.6K tokens at p50 and 19K at p90. That's above the 6K top row of the
  model cost grid (#155), so the digest needs a per-window text budget, not
  just de-duplication. Titles, URLs and apps alone are small (p50 under 1K
  characters).
- **Model pick (#158):** plan on 60 to 100 active windows a workday, up to
  about 200 if no-AFK-data windows count, and recompute the cost at the
  digest's chosen budget.
- **Which time a run covers (#159):** decide what to do with windows that
  have signals but no AFK verdict.

## Reproduce

```bash
python -I docs/research/measure_windows.py \
  "$HOME/Library/Application Support/ComputerHistory-dev/history.db"
```

The shingle check: for each window, walk its `ax-text` and `screenshot`
signals in time order, split on whitespace, and count a word's characters only
when the 8-word tuple starting at it is new in that window.
