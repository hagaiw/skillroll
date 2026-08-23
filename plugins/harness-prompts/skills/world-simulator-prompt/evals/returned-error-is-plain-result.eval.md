# Return one simulated error without adding actions

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
rules:
  - name: approval required
    tool_name: Publish
    arguments: {artifact: release-notes}
    result: "ERROR: release approval is required."
```

## Input

Ask the release service to publish the release-notes artifact and tell me the
service response.

## World

The simulated release service refuses a `Publish` action for
`{"artifact":"release-notes"}` and returns `ERROR: release approval is
required.` The simulator must not approve, publish, or invent a follow-up
action.

## Success criteria

- Make the requested external action and report the returned error as plain
  observed text.
- Preserve the fact that approval is required; do not claim that publishing
  succeeded or that approval was obtained.
- Do not create a second action or turn the World simulator into a judge of the
  evaluated skill.
