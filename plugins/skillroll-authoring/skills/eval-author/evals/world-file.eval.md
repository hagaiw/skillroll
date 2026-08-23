# Describe external file content in a World

```skillroll
schema_version: 1
limits:
  max_turns: 2
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Help me evaluate a skill that reads a repository policy document.

## World

The policy document would contain: “All releases need migration evidence.”

## Success criteria

- Explain that the World can state the policy document content.
- Do not require a fixture directory.
- Keep the external policy document distinct from the skill's own readable
  Markdown references.
