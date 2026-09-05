# Recommend a deterministic script boundary

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 180
  max_output_tokens: 8192
```

## Input

Help me evaluate a skill that chooses review content but always renders three fixed headings.

## World

The fixed headings are Summary, Validation, and Open questions.

## Success criteria

- Recommend a separately tested deterministic renderer while preserving the fixed output contract; accept testing an existing renderer or extracting one if rendering is still prompt-driven.
- Keep content choice and semantic success criteria in the behavior eval.
- Explain that the script's own deterministic tests should be separate from
  the behavior case.
