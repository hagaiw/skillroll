# Write an evidence-calibrated offline authoring handoff

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 180
  max_output_tokens: 8192
```

## Input

Finish the SkillRoll authoring task with a short handoff that another
maintainer or AI-assisted reviewer can understand without the original task
conversation. Summarize the cases and deferrals, explain what the evidence
means, and recommend the smallest next action. Do not imply that a live model
run happened.

Authoring record from the completed task:

SkillRoll is the repository's drop-in eval harness for Agent Skills. Each
Markdown case describes a request, a Dungeon Master simulation of the outside
world, and the behavior that should succeed. The offline authoring pass
inspected 7 skills and selected 2. It added these two files:

- `skills/incident-summary/evals/no-invented-cause.eval.md`, which checks that
  incomplete incident evidence is reported without inventing a root cause.
- `skills/release-review/evals/unsafe-publish.eval.md`, which checks that an
  unauthorized release is stopped and the missing approval is requested.

Both cases passed `skillroll validate` offline. No model key was configured,
so no model-backed eval, samples, no-skill comparison, or regression-sensitive
damaged-skill run exists. The `skills/document-renderer/SKILL.md` skill was
deferred because its important result is a rendered PDF that needs an actual
renderer and visual inspection. The remaining four inspected skills were not
selected because they were lower-priority or depended on unavailable external
services. No current skill defect was found because no model-backed behavior
was run.

## World

The completed authoring record is supplied in Input. No additional external
evidence is needed to summarize it, and no live run is authorized.

## Success criteria

- Identify the inspected scope and the small offline eval-authoring batch in understandable terms; do not require a particular opening, heading, or product introduction.
- Name both added paths and their behaviors, and make their offline-only evidence status clear; a shared statement applying to both cases is sufficient, without repeated per-case labels or unsupported behavioral claims.
- Name the deferred document-renderer path and explain that visual PDF output
  needs renderer and inspection evidence outside this run. Make clear that
  the other four skills were not selected rather than silently implying full
  repository coverage.
- State that offline validation passed, no model-backed eval or no-skill comparison ran, and no current defect was established. Recommend review or exploratory evaluation without promoting the cases to blocking CI; no CI disclaimer is needed if CI is not proposed.
- Keep the handoff concise and independently understandable: include the
  affected paths, evidence boundary, limitation, and next action without
  requiring a repository search or the hidden authoring conversation.
