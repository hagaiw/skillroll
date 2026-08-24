# Pin local main and target before setup

```skillroll
schema_version: 1
limits:
  max_turns: 8
  timeout_seconds: 180
  max_output_tokens: 1500
```

## Input

Prepare the preregistered `nora/ops-notes` repository for a blind trial using
the current local SkillRoll main. Set up the temporary checkout and give the
authoring worker a preparation manifest. Do not spend inference yet.

## World

The target manifest specifies canonical URL `https://example.test/nora/ops-notes`,
target revision `1111111111111111111111111111111111111111`, and skills root
`skills` containing `skills/incident-notes/SKILL.md` and
`skills/handoff/SKILL.md`. A fresh temporary clone can be checked out at that
revision.

The local SkillRoll repository is on clean branch `main` at revision
`2222222222222222222222222222222222222222`. Its remote has not been fetched in
this task, so remote freshness is unknown. Building or installing from that
exact local commit succeeds. `skillroll init --skills-path skills --yes`
creates `skillroll.toml` without inference, and offline validation passes.
Neither `doctor` nor `eval` runs.

## Success criteria

- Use exact target revision `1111111111111111111111111111111111111111` in an
  isolated temporary checkout rather than following a moving branch.
- Build or install SkillRoll from exact clean local-main revision
  `2222222222222222222222222222222222222222`, not from a published package.
- Record that remote freshness was not checked instead of claiming this is the
  latest remote revision.
- Initialize the discovered `skills` root and run offline validation, while
  clearly stating that no `doctor` or live inference was run.
- Return a manifest with both SHAs, clean state, skills root, generated paths,
  and commands, without modifying the user's SkillRoll checkout.
