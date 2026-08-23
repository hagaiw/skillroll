# Combine a two-step flow

```skillroll
schema_version: 1
rules:
  - name: summary step
    tool_name: Skill
    arguments: {name: summarize-change}
    result: "Artifact: summary. Evidence: two files changed."
  - name: risk step
    tool_name: Skill
    arguments: {name: assess-risk}
    result: "Artifact: risk. Evidence: migration needs review."
```

## Input

Run `summarize-change` and then `assess-risk`; combine their artifacts.

## World

The two named Skill actions return the declared artifacts in order.

## Success criteria

- Request both named steps as `Skill` actions and identify their evidence in the
  combined result.
- Preserve the migration uncertainty.
