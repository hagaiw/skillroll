# Write a complete PR overview

```skillroll
schema_version: 1
checks:
  - name: PR overview renderer self-test
    command: python3 plugins/pr-overview/skills/pr-overview/scripts/render_overview.py --self-test
    covers: [scripts/render_overview.py]
```

## Input

Create an overview: the PR adds timeout validation, its unit tests pass, and migration coverage remains open.

## World

The supplied sentence is the complete pull-request evidence.

## Success criteria

- Include Summary, Validation, and Open questions content.
- Keep the missing migration coverage as an open question.
