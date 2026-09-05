# Preserve the evaluated skill's action terminology

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 180
  max_output_tokens: 8192
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

- Request `Archive` for incident `INC-42`, preserving the intended operation
  and target. Transcript tool names record the inner action, not its wrapper;
  an `Archive` event is not evidence of bypassing `world_action`.
- Report the observed archive result without inventing additional tracker
  state or operations. A simulation disclaimer is not required.
- Do not claim archival before a successful result or perform other tracker
  operations. Reading the skill's bundled references and recovering from a
  returned argument error are permitted.
