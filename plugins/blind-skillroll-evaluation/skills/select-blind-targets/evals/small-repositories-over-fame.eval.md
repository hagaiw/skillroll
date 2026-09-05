# Prefer small targeted repositories over famous catalogs

```skillroll
schema_version: 1
limits:
  max_turns: 4
  timeout_seconds: 180
  max_output_tokens: 1400
```

## Input

Select three new public Agent Skills repositories for a blind SkillRoll trial.
The product is mainly intended for individuals and small teams, so make the
batch representative of them rather than selecting the most recognizable
projects. Return a preregistration I can hand to another evaluator. Discovery
has already produced the verified candidate set below; select from it without
performing another search.

- `famous/platform-skills`, 42,000 stars, 237 active skills, revision `aaaa...`.
- `vendor/reference-skills`, 19,000 stars, 26 active skills, revision `bbbb...`.
- `lee/meeting-notes-skill`, 18 stars, skills root `.`, active path `SKILL.md`,
  revision `1111111111111111111111111111111111111111`.
- `devon/release-helper`, 7 stars, skills root `skills`, active paths
  `release/SKILL.md`, `changelog/SKILL.md`, `approval/SKILL.md`, and
  `rollback/SKILL.md`, revision `2222222222222222222222222222222222222222`.
- `sam/data-cleanup-skills`, 31 stars, skills root `skills`, active paths
  `csv/SKILL.md`, `json/SKILL.md`, `dedupe/SKILL.md`, `normalize/SKILL.md`,
  `redact/SKILL.md`, and `report/SKILL.md`, revision
  `3333333333333333333333333333333333333333`.
- `org/skill-fixtures`, 2 stars, 3 active skills plus 80 fixture `SKILL.md` files,
  revision `4444444444444444444444444444444444444444`.

Their canonical URLs are `https://github.com/<owner>/<repository>` and their
licenses permit this temporary trial. The three small repositories cover a
personal workflow, a small-team release workflow, and a compact data workflow.
The large repositories add fame but no missing task shape. No SkillRoll result
was opened.

## World

No external interaction is needed. The verified discovery artifact is included
in Input.

## Success criteria

- Select `lee/meeting-notes-skill`, `devon/release-helper`, and
  `sam/data-cleanup-skills`, explaining their small-team fit and useful
  variation rather than favoring star count.
- Do not select either large catalog, and distinguish active skills from the
  fixture files instead of treating raw recursive `SKILL.md` count as scope.
- Preregister each selected repository with its canonical identity, exact full
  revision, skills root or active skill paths, and selection rationale.
- Keep the handoff blind: do not predict outcomes, invent prior results, or
  recommend dropping a target based on how it might score.
