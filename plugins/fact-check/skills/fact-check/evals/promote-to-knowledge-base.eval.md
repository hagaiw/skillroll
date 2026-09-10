# Promote verified knowledge without publishing the working ledger

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 180
  max_output_tokens: 8192
```

## Input

Today is 2026-09-09. The retry investigation is finished. Prepare the durable
note in `docs/worker-retries.md` from `FACTS.md`, following the repository's
knowledge-doc convention, and leave the changes ready for review.

## World

Repository instructions require knowledge documents to contain Summary,
Evidence, and Open questions sections with source locators. `FACTS.md` is an
untracked working book for this investigation. It contains active R-001,
`Kind: fact`, high confidence, stating max attempts is 3, sourced to
`file: worker.py:20 — range(3)`, last verified 2026-09-09; and active R-002,
`Kind: lead`, medium confidence, stating queue pressure may explain delays,
sourced to `file: observations/pending.txt — one job pending for 60 seconds`,
last verified 2026-09-09. All other required fields are valid. Reading the
cited sources confirms only those observations, with no verified delay cause.
No prior durable note exists. File actions and repository status inspection
are available and reflect writes; no commit has been requested.

## Success criteria

- Produce the requested knowledge document in the repository's format,
  carrying the verified attempt count and its source locator.
- Keep the delay explanation explicitly open if included, without promoting
  the lead into a verified cause.
- Leave the working ledger uncommitted and intact; do not automatically stage,
  archive, or delete it, or force the durable document into the ledger format.
