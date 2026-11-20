# Pull requests

Every pull request description follows this shape. Sections 1 to 5 fit on one
screen; proof goes in section 6, collapsed. Write for a reviewer who has not
seen the work: plain language, full sentences, no ticket shorthand.

## The shape

1. **What this does**: two or three sentences.
2. **Walkthrough**:
   - **New files**: each file created and why it exists.
   - **Data models**: record formats, tables and types created or changed.
   - **Workflow**: how the code flows end to end, as numbered steps.
   - **Key functions**: the high-level functions and methods added, and what
     each does.
3. **How to review**: the order to read files in, and what is skim-only
   (fixtures, generated output, renames).
4. **Decisions that need your eye**: judgment calls only, one line each.
   Write "None" when there are none.
5. **Not proven here**: what no automated check covers, such as anything
   that needs a real Mac, a permission or a later ticket.
6. **Evidence**, inside `<details>` blocks, pasted from real runs and never
   summarised:
   - the final lines of each check command that was run;
   - where CLI behaviour changed, a transcript of the real commands against
     an isolated run (the `verify-computer-history` skill);
   - for the main behaviour, the test that fails without the change;
   - review findings and what was done about each.

A section that does not apply says "None"; it is never dropped.

## Keeping the diff reviewable

- A rename or other mechanical change goes in its own commit with nothing
  else in it.
- A pull request with more than about 600 changed lines of hand-written code
  is split before review.
- `.github/pull_request_template.md` holds the same headings; keep the two in
  step.
