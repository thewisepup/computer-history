# Choosing what to send the classifier

Brainstorm, 2026-11-19. Ahead of M5 (classification): out of everything the
sources capture, what is the smallest, most useful context to send so a model
can tell which **project** and **type of work** a stretch of activity belongs
to?

Status: ideas plus one set of measurements on live data. Nothing here is
decided; the open questions at the end say what has to be measured first.

## The framing

A 5-minute window holds tens to hundreds of KB of raw captures. The job is to
compress that into a digest that keeps classification accurate. The number to
optimise is **classifier accuracy at a fixed token budget**; every technique
below either raises accuracy or lowers the budget.

## What the live data looks like today

Measured on 2026-11-19 against the local database (597 `ax-text` captures,
about 1.5 days of use). Each capture's payload is the spool record described
in `capture-agent/README.md`; signals are built by
`computer_history/sources/ax_text/normalize.py`.

| Measure | Value |
|---|---|
| Captures whose text exactly matches an earlier capture (`text_sha256`) | 167 of 597 (28%) |
| …identical to the previous capture of the same app (static screen, heartbeat) | 123 |
| Share of text in lines that recur in 10 or more captures | 52% |
| Capture window titles that name the project | 337 of 597 (56%) |
| Capture texts that mention the project | 284 of 597 (48%) |
| Median capture size by app | T3 Code 7.5 KB · Discord 10 KB · Chrome 3.4 KB (largest 167 KB) |
| `ax-text` signals containing private-use icon characters (U+E000–U+F8FF) | 44 of 529 |

What it shows:

- **Most recurring text is app interface:** chat input placeholders, undo
  toasts, the machine name, editor file trees. Rich text arrives in fragments
  (lone `.`, `,`, `(`, `and`), one per link or code span, because each is its
  own accessibility element.
- **Titles carry most of the project signal for development work.** They name
  the project more often than the captured text does.
- **Text matters when the title is vague** ("T3 Code (Beta)", "New Tab", chat
  channels, terminals, meetings) and for **type of work**: reading a PR,
  writing a spec and debugging can all sit under one title.
- **Signals already lose information.** The agent keeps up to 50 KB with line
  breaks (`CappedText.swift`); `clean_text` collapses all whitespace and caps
  the signal at 10,000 characters (`computer_history/text.py`,
  `MAX_AX_TEXT_LENGTH`). The full text survives only in
  `observations.payload`.
- **Side effect of the accessibility switch:** turning on accessibility for
  Electron apps (`AccessibilityFlag.swift`) makes Cursor show "Screen reader
  usage detected…", and that sentence lands in captures.

Keep capturing everything. Raw observations are immutable and signals are
rebuildable (AGENTS.md), so noise costs a few MB a day while text never
captured is lost for good. Identical heartbeats also prove presence for
`status` coverage. The real cost of capturing everything is privacy, which
argues for a wider denylist, not for less content.

## Techniques

### 0. Measure first

- **A labelled set:** hand-label one or two days with project and type of work.
- **Teacher and student:** a large model labels windows from *all* raw text
  (the teacher); measure how well a cheap digest plus a cheap model (the
  student) agrees with it. The teacher can label far more data than a person.
- **Budget curves:** accuracy against tokens for title only → + URL →
  + extracted terms → + cleaned text → + raw text. The point where the curve
  flattens sets the budget.
- **Leave one out:** remove one field at a time to see what earns its tokens.
- **Corrections:** once M6 ships, every user correction is a free label.

### 1. Rule-based cleanup (no model)

- **Exact repeats:** drop by `text_sha256`, already on every record.
- **Near-repeats:** MinHash or SimHash catch pages that changed by a line.
- **App interface:** lines frequent across one app's captures are its chrome;
  learn them from the data per app instead of writing rules.
- **Bursty terms:** rare over the week but frequent this hour means current
  topic (TF-IDF against your own history).
- **Only what's new:** for repeat captures of the same window, keep new lines.
- **Weight by time on screen:** use aw-window durations.
- **Extract specific terms:** file paths, repo names, URLs, branch names,
  ticket keys (`ABC-123`, `#28`), headings, error messages; the strongest
  project cues per token.
- **Keyphrases:** YAKE, RAKE or KeyBERT for a handful of phrases per window.
- **Strip private-use icon characters** in `clean_text` (about a one-line
  change).

### 2. Better raw material from the agent

- **Structured attributes instead of text:** many native apps report the open
  file on the window (`AXDocument`), browsers report `AXURL`, and the focused
  element and selected text show what the user is acting on. One file path can
  name the project. Which of the apps in use actually expose these is
  unmeasured; `.scratch/m2-capture-agent/ax-measure/` is the tool to adapt.
- **Keep the element type:** the agent flattens everything into plain text
  (`WindowWalk.swift`). A light tag (heading, editor, sidebar) would let the
  cleanup step keep editor content and drop sidebars.
- **Per-app readers for the busiest apps:** terminal (commands, current
  folder), editor (file, repo), browser (URL, main heading), chat (channel),
  meetings (title). The generic path covers the long tail.

### 3. Sources that already know the answer

Join in sources that name the project directly and use them as anchors for
nearby windows:

- git commits and branch checkouts (time plus repo)
- shell history with each command's folder
- calendar events (title, attendees)
- GitHub or the issue tracker: PR or issue URL → title, repo, labels
- AI chat transcripts (Claude Code, T3 threads)

### 4. Statistics and embeddings

- **Nearest project:** embed windows and compare with each confirmed
  project's average embedding; easy cases need no LLM.
- **Cascade:** a cheap classifier (e.g. on titles, domains, terms, trained on
  corrections) takes confident cases; only uncertain windows go to the LLM.
- **Nearby examples:** retrieve similar labelled windows as few-shot examples.
- **Split by task switch:** cut where content shifts sharply instead of every
  5 minutes; windows that straddle two tasks are the hardest to classify.
- **Smoothing over time:** consecutive windows usually share a project; a
  model that prefers continuity (an HMM or simple stickiness) reduces jumpy
  labels. Time of day and app-to-project habits help too.
- **Ask about the right windows:** have the user label the windows the model
  is least sure of.

### 5. Let an LLM choose what to pass

- **Two stages:** a small local model writes one line plus key terms per
  window; the main model classifies those. Raw text stays on the Mac.
- **Ask for more:** send a cheap digest first and let the model request detail
  through a tool ("full text of capture X", "terminal at 14:05"). This fits
  the MCP design.
- **Learn what mattered:** have the teacher cite the lines it used, then train
  a cheap line scorer (or derive rules) that predicts useful lines.
- **Prompt compression:** LLMLingua drops low-information tokens using a small
  model; a quick generic baseline.
- **Summaries at several levels:** window → hour → day, plus a running
  "current task" carried forward.

### 6. Privacy

Every step that shrinks the digest also shrinks what leaves the Mac for
OpenRouter. Redact secrets, email addresses and message bodies at the digest
step; a local first-stage model keeps raw text on the machine entirely.

## Suggested order

1. Labelled day plus teacher labels; the budget curve.
2. Baseline: title, app and URL only.
3. Rule-based cleanup: repeats, app interface, new lines only, specific terms.
4. Structured attributes from the agent (`AXDocument`, `AXURL`, focused
   element).
5. Joins with git, calendar and the issue tracker.
6. Cascade: embedding or simple classifier first, LLM only when uncertain.
7. Later: learned line scoring; letting the LLM ask for more.

Steps 1–3 run on data already stored. Step 4 is the likeliest high-value
agent change.

## Open questions

- How accurate is title + app + URL alone on a labelled day? This decides how
  much the text pipeline is worth.
- Which apps in daily use expose `AXDocument`, `AXURL` and a useful focused
  element?
- What token budget per window keeps accuracy within a few points of the
  teacher?
- Does splitting by task switch beat fixed 5-minute windows on mixed windows?

## How the numbers were measured

Read-only queries against `~/Library/Application Support/ComputerHistory/history.db`
on 2026-11-19 (about 23:30 UTC):

- Exact repeats: count of `kind = capture` payloads minus distinct
  `text_sha256`; same-app repeats compare each capture's hash with the
  previous capture of the same `app_name`.
- Recurring lines: each capture's text split on newlines and stripped; a line
  counts as recurring if it appears in 10 or more captures; share is by
  characters.
- Project mentions: `window_title` or `text` containing `computer-history`
  (text also `computer_history`).
- Icon characters: signals whose `text` contains a code point in
  U+E000–U+F8FF.

## References

- MinHash: A. Broder, "On the resemblance and containment of documents", 1997.
- SimHash: M. Charikar, "Similarity estimation techniques from rounding
  algorithms", STOC 2002.
- RAKE: S. Rose et al., "Automatic keyword extraction from individual
  documents", 2010.
- YAKE: https://github.com/LIAAD/yake
- KeyBERT: https://github.com/MaartenGr/KeyBERT
- LLMLingua: https://github.com/microsoft/LLMLingua
- macOS accessibility attributes (`AXDocument`, `AXURL`,
  `AXFocusedUIElement`): Apple's Accessibility API documentation for
  `AXUIElement`.
