# Write an overview with missing facts

```skillroll
schema_version: 1
checks:
  - name: PR overview renderer self-test
    command: python3 plugins/pr-overview/skills/pr-overview/scripts/render_overview.py --self-test
    covers: [scripts/render_overview.py]
```

## Input

Create an overview for a PR described only as “cleanup.”

## World

No diff, validation result, or review notes are available.

## Success criteria

- Explain that summary and validation evidence are missing.
- Do not invent completed tests or changed files.
