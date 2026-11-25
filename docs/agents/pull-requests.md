# Pull requests

Every pull request description follows this shape. The reader skims the top
four sections to decide how hard to look and flag anything wrong, then opens
the collapsed sections for detail. Write in plain bullets for a reviewer who
has not seen the work.

## Writing rules

- Bullets, one idea each, one or two lines long. No paragraphs.
- The top four sections use plain words. Leave out function names, internal
  terms, milestone and ticket numbers. If a sentence only makes sense to
  someone who read the code, rewrite it or move it into the Walkthrough.
- Say each thing once and in one place.
- A section that does not apply says "None". Never drop a section.

## The shape

1. **What this does**: 2 to 5 bullets on what changes, starting with what
   behaves differently. For example, "The backend runs from a stable install
   that only takes commits that passed CI", not "Implements M4".
2. **Why you should care**: 1 to 3 bullets on what this gets you, by kind of
   change:
   - feature: what the user can now do, or no longer has to worry about;
   - refactor: what got simpler and why it is simpler;
   - schema or storage change: the effect on performance and on features;
   - fix: what was broken and who it hit.

   End with one line, `Review effort: skim | read | careful`, and the reason
   (for example, "careful: touches live data").
3. **Call-outs**: one sentence per item, each tagged:
   - `[Action]` something you must do (merge order, a new dependency, steps
     after merging), in one line; the steps themselves go in Try it yourself;
   - `[Choice]` a judgment call you might overrule, stated as what was chosen;
   - `[Gap]` something no automated check covers (needs the real Mac, a
     permission, a TLA+ run, a later ticket).

   Write "None" when there are none. No rationale paragraphs: if the reason
   takes more than a clause, it goes in the Walkthrough.
4. **Testing**: what was run and the verdict, in 2 to 4 bullets. For example,
   "CI green (9/9)" or "ran install, update and a forced fallback against an
   isolated run; the fallback restored the backup". Then the evidence,
   collapsed, pasted from real runs and never summarised:
   - the final lines of each check command;
   - where CLI behaviour changed, a transcript of the real commands against
     an isolated run (the `verify-computer-history` skill);
   - screenshots where there is something to see (a notification, a menu,
     `status` output, an app window), taken from isolated or synthetic runs
     only, never live data, since the repository is public. Upload them to the
     `pr-evidence` branch under `<pr-number>/` and embed them as
     `![what it shows](https://github.com/thewisepup/open-computer-history/blob/pr-evidence/<pr-number>/<file>.png?raw=true)`;
   - the test that fails without the change;
   - review findings and what was done about each.
5. **Try it yourself**: what only you can check, as copy-paste steps from the
   `pr-checklist` skill. Each step says whether it runs in the dev checkout or
   the stable install, the exact command, what to expect and how long to wait.
   Steps needed after merging (`computer-history update`, reinstalling the
   capture agent, a permission or a re-login) go under **After merging**.
   Anything a command can show is checked by the agent and lands in Testing
   instead. With nothing left for you, write "Nothing to do by hand: all
   checked above."
6. **Walkthrough**, collapsed, written with the `pr-walkthrough` skill:
   - **New files**: each file created and why it exists.
   - **Data models**: record formats, tables and types created or changed,
     each with a sample value before and after.
   - **Workflow**: how the code flows end to end, as numbered steps.
   - **Key functions**: the high-level functions and methods added, and what
     each does.
7. **How to review**, collapsed: the order to read files in, and what is
   skim-only (fixtures, generated output, renames).
8. **Notes**: bookkeeping. The milestone or spec, "folds the milestone's
   stack into one PR", `Closes #…`, and follow-ups.

## Example

Illustrative, the top of a refactor:

```markdown
## What this does
- Only the ActivityWatch adapter reads ActivityWatch now. Ingest, backfill
  and the tests all go through the same two calls.
- Six helpers that leaked out of the adapter are now private.
- No change to what is captured or stored.

## Why you should care
- There is one place that decides where to resume reading ActivityWatch, so
  the tests exercise exactly what production runs.
- Review effort: skim. It's a pure refactor and CI covers it.

## Call-outs
- [Choice] Kept `pull.py` as its own file rather than merging it into a
  ~300-line adapter.
- [Action] Conflicts with #127 in two export lists: keep #127's names.
```

## Keeping the diff reviewable

- A rename or other mechanical change goes in its own commit with nothing
  else in it.
- A pull request with more than about 600 changed lines of hand-written code
  is split before review.
- `.github/pull_request_template.md` holds the same headings, and
  `tests/unit/test_standards.py` fails when the two drift.
