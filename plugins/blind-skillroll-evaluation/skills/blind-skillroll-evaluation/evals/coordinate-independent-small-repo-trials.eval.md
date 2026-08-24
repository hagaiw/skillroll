# Coordinate independent small-repository trials

```skillroll
schema_version: 1
limits:
  max_turns: 6
  timeout_seconds: 180
  max_output_tokens: 1800
rules:
  - name: complete flow
    tool_name: Skill
    arguments: {name: flow-runner}
    result: "Selection: solo-notes@1111111111111111111111111111111111111111 (scope skills/notes/SKILL.md), release-helper@2222222222222222222222222222222222222222 (4 active skills below skills/), and data-cleanup@3333333333333333333333333333333333333333 (6 active skills below skills/), selected before outcomes. Preparation: three isolated trials used clean local SkillRoll main 5555555555555555555555555555555555555555; offline validation passed. Authoring: fresh target-specific workers froze case paths and hashes without prior reports. Live model openai/gpt-5.6-luna-pro: solo-notes/evals/source-boundary.eval.md PASS run-101 usage 1800; solo-notes/evals/uncertainty.eval.md PASS run-102 usage 1700; release-helper/evals/wait-ci.eval.md FAIL TARGET_BEHAVIOR run-103 usage 2100; release-helper/evals/approval.eval.md PASS run-104 usage 1900; data-cleanup/evals/preserve-source.eval.md FAIL TARGET_BEHAVIOR run-105 usage 2200; data-cleanup/evals/missing-input.eval.md ERROR PROVIDER_ENVIRONMENT run-106 usage unavailable. No repository commands, commits, pushes, or publishing ran."
```

## Input

Run an end-to-end blind evaluation of the current local SkillRoll main against
three new external repositories representative of individual developers and
small teams. Live inference is authorized within the supplied budget. Keep the
trials independent and report the evidence.

## World

The installed flow runner executes the four named component skills in order and
returns the deterministic phase artifacts shown in its rule. Each selected
target has one to six active skills. The
temporary workspaces and inference key are already authorized. No repository
commands, commits, pushes, or published changes are authorized.

## Success criteria

- Use the installed flow runner to execute selection before preparation,
  preparation before blind authoring, and authoring before live running; do not
  merely describe the process.
- Use the returned target names, active scopes, exact SkillRoll and target
  revisions, and keep each target in an isolated workspace.
- Preserve blindness by using the fresh authoring artifacts without passing
  prior reports or one target's outcomes into another target's authoring phase.
- Treat the six live runs—not setup or offline validation—as the behavioral
  signal, and report their case paths, model, run IDs, available usage, outcome
  classifications, and exact total of 3 PASS, 2 FAIL, and 1 ERROR.
- State that repository commands, commits, pushes, and publishing did not run,
  and keep any generated CI advisory.
