# Metamorph Knowledge Platform

Follow the engineering principles in @docs/engineering-principles.md before proposing or writing any fix to extraction, cleaning, rendering or parsing. In short:
- build the simplest pipeline that keeps legal information clean enough for retrieval;
- fix only problems meaningful across documents, with general rules and never document-specific ones;
- checks warn, and fallbacks need strong evidence.
