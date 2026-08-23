# Execute with one bounded world action

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
rules:
  - name: bundled context
    tool_name: Read
    arguments: {path: references/context.md}
    result: "The executor may request one generic world_action tool; returned values are observed evidence."
```

## Input

Read the bundled executor context and summarize the tool and evidence boundary
for a maintainer who has not seen this repository before.

## World

The selected skill bundle contains `references/context.md`. A `Read` request for
that exact path returns the reference text supplied by the deterministic rule.
No other filesystem, shell, network, or nested-agent access is available.

## Success criteria

- Use the one available `world_action` tool to request the bundled reference,
  then base the final explanation on the returned result.
- Explain that the evaluated skill has one generic action boundary and that
  returned values are evidence; do not claim access to arbitrary host files or
  other agents.
- Give a concise explanation without exposing eval metadata as if it were part
  of the user's request.
