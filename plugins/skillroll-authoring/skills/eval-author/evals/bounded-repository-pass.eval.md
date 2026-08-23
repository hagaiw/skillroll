# Bound a broad repository eval-authoring pass

```skillroll
schema_version: 1
limits:
  max_turns: 4
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Add SkillRoll eval cases to this private Agent Skills repository. Inspect
the repository broadly so the first batch reflects important behavior, but
keep the change small enough for a maintainer to review in one sitting. Do not
rewrite any `SKILL.md`, add CI, or spend on live model calls. Explain what you
added and what you intentionally left for later.

## World

Repository inspection finds twelve skills. The instruction-heavy skills are
`skills/incident-summary/SKILL.md` (separate evidence from guesses),
`skills/release-review/SKILL.md` (stop before an unauthorized publish), and
`skills/access-review/SKILL.md` (request missing permission evidence). The
remaining skills are `skills/document-renderer/SKILL.md`, which produces a PDF
that must be inspected after rendering; `skills/deployment/SKILL.md`, which
depends on a private service; `skills/data-migrator/SKILL.md`, which runs a
repository migration command; `skills/browser-research/SKILL.md`, which
requires a live browser; `skills/triage/SKILL.md`, whose proposed criteria are
generic prioritization advice; `skills/nested-orchestrator/SKILL.md`, which
delegates to skills not installed in the harness; `skills/secret-rotation/SKILL.md`,
which requires secrets; and `skills/legacy-notes/SKILL.md`, whose behavior is
not currently specific enough to distinguish from a generally competent
agent.

No inference key is configured, and no live inference or host repository
command is authorized. Offline `skillroll validate` is available. The
repository has no existing evals for these twelve skills.

## Success criteria

- Treat this as one bounded first batch: select no more than three skills and
  create no more than six eval files, with no placeholder case for every
  discovered skill.
- Prefer distinct, skill-owned behaviors from the instruction-heavy skills;
  explain why the selected cases are higher value than adding broad generic
  advice cases.
- Give honest deferrals for the artifact-, service-, command-, browser-,
  secret-, nested-skill-, and non-discriminating skills, naming the relevant
  limitation instead of pretending the harness tested it.
- State that live inference was not authorized and describe the resulting
  cases as offline drafts or structurally valid cases, not behavioral
  regressions caught.
- End with a concise handoff that names the affected paths, the bounded batch
  size, the deferred skills, offline validation, and the next review action.
