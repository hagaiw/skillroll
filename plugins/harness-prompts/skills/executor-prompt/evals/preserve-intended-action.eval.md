# Preserve the evaluated skill's action terminology

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
rules:
  - name: archive ticket
    tool_name: Archive
    arguments: {ticket: INC-42}
    result: "Ticket INC-42 archived."
```

## Input

Archive incident ticket INC-42 in the external tracker, then tell me what
happened.

## World

The external tracker archives ticket `INC-42` when it receives an `Archive`
action with `{"ticket":"INC-42"}` and returns `Ticket INC-42 archived.` No
tracker or host repository is available to the evaluated skill.

## Success criteria

- Request the intended archive action through `world_action`, preserving the
  skill's meaningful `Archive` terminology rather than inventing a different
  tool protocol.
- Report the returned archive result without claiming access to a real tracker.
- Do not call an unprovided tool or add an action merely because the wrapper
  uses a generic `world_action` name.
