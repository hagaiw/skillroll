# Recommend a deterministic script boundary

```skillroll
schema_version: 1
limits:
  max_turns: 2
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Help me evaluate a skill that chooses review content but always renders three fixed headings.

## World

The fixed headings are Summary, Validation, and Open questions.

## Success criteria

- Recommend extracting only the fixed renderer to a separately tested script.
- Keep content choice and semantic success criteria in the behavior eval.
- Explain that the script's own deterministic tests should be separate from
  the behavior case.
