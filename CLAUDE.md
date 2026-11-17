# Metamorph Knowledge Platform

Follow the engineering principles in @docs/engineering-principles.md before proposing or writing any fix to extraction, cleaning, rendering or parsing. In short:
- build the simplest pipeline that keeps legal information clean enough for retrieval;
- fix only problems meaningful across documents, with general rules and never document-specific ones;
- checks warn, and fallbacks need strong evidence.

## Agent skills

### Issue tracker

Issues and specs live as local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix), recorded as a `Status:` line in each issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
