# Domain docs

Domain terms live in `GLOSSARY.md` at the repo root; there is no `CONTEXT.md`
and no `docs/adr/` yet. When a skill asks for `CONTEXT.md`, read
`GLOSSARY.md` instead.

- When your output names a domain concept (an issue title, a test name, an
  identifier), use the glossary's term, never a word in its _Avoid_ list.
- A concept missing from the glossary is either invented language (reconsider)
  or a real gap: add the entry in the same change (CODING_STANDARDS.md H12).
- If your output contradicts a recorded decision, say so explicitly rather
  than silently overriding it.
