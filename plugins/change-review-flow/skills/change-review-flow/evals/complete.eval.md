# Coordinate a complete review

```skillroll
schema_version: 1
rules:
  - name: runner result
    tool_name: Skill
    arguments: {name: flow-runner}
    result: "Summary: config changed. Risk: migration needs review. Review: request migration evidence."
```

## Input

Review a change that updates the configuration format.

## World

The installed flow runner returns the three labeled artifacts shown in its rule.

## Success criteria

- Use the flow-runner artifact to produce a concise review.
- Request migration evidence rather than asserting the migration is safe.
