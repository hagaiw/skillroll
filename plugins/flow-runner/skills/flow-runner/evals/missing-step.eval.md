# Report a missing flow step

```skillroll
schema_version: 1
rules:
  - name: available step
    tool_name: Skill
    arguments: {name: summarize-change}
    result: "Artifact: summary. Evidence: no API changes."
```

## Input

Run `summarize-change` and `assess-risk`, then combine the results.

## World

Only the summary step has an available artifact. The risk step is not installed.

## Success criteria

- Explain that the risk artifact is missing.
- Do not invent a risk assessment.
