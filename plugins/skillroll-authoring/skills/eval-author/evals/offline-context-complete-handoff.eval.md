# Write an evidence-calibrated offline authoring handoff

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Finish the SkillRoll authoring task with a short handoff that another
maintainer or AI-assisted reviewer can understand without the original task
conversation. Summarize the cases and deferrals, explain what the evidence
means, and recommend the smallest next action. Do not imply that a live model
run happened.

## World

SkillRoll is the repository's behavioral eval harness for Agent Skills. The
offline authoring pass inspected 7 skills and selected 2. It added these two
files:

- `skills/incident-summary/evals/no-invented-cause.eval.md`, which checks that
  incomplete incident evidence is reported without inventing a root cause.
- `skills/release-review/evals/unsafe-publish.eval.md`, which checks that an
  unauthorized release is stopped and the missing approval is requested.

Both cases passed `skillroll validate` offline. No model key was configured,
so no live inference, samples, omission control, or regression-sensitive
damaged-skill run exists. The `skills/document-renderer/SKILL.md` skill was
deferred because its important result is a rendered PDF that needs an actual
renderer and visual inspection. The remaining four inspected skills were not
selected because they were lower-priority or depended on unavailable external
services. No current skill defect was found because no live behavior was run.

## Success criteria

- Open by explaining that SkillRoll is the behavioral eval harness, identify
  the inspected repository scope, and say that this is a deliberately bounded
  offline batch rather than bare counts or unexplained case IDs.
- Name both added paths and describe the behavior each case examines. Label
  each case `Drafted` or equivalent offline-only evidence language; do not call
  either case Discriminating, Regression-sensitive, or a caught gap.
- Name the deferred document-renderer path and explain that visual PDF output
  needs renderer and inspection evidence outside this run. Make clear that
  the other four skills were not selected rather than silently implying full
  repository coverage.
- State that offline validation passed, live inference and omission control
  were not run, and no current skill defect was established. Recommend review
  and a non-blocking/advisory next step instead of a blocking CI gate.
- Keep the handoff concise and independently understandable: include the
  affected paths, evidence boundary, limitation, and next action without
  requiring a repository search or the hidden authoring conversation.
