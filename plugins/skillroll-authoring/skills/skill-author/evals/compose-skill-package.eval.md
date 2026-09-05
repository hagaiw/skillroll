# Compose a compact skill package by responsibility

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 180
  max_output_tokens: 8192
```

## Input

I am designing a skill for preparing release-note drafts from incident reports.
It should apply only to release-note drafting, preserve the user’s requested
audience, stop before publishing when approval status is missing, support
audience-specific policy that may grow over time, and apply the same redaction
and heading-normalization steps to every draft.

Please propose a small package design for review, including what belongs in
`SKILL.md` and whether any reference or script is warranted. Do not edit files or
run commands yet.

## World

No external interaction is needed. This is a design-only request; no files or
scripts have been created or executed.

## Success criteria

- Define one coherent purpose and a discriminating routing description rather
  than a general writing skill.
- Keep essential routing, the normal workflow, and the no-publish-without-
  approval boundary in `SKILL.md`.
- Place substantial audience-specific conditional policy in a linked reference
  instead of inflating the entrypoint.
- Place repeated redaction and heading normalization in a deterministic script,
  while leaving content and audience decisions to the prompt.
- Clearly present the result as a design proposal; distinguish structural
  validation, script tests, and live behavioral evidence, without claiming any
  were performed.
