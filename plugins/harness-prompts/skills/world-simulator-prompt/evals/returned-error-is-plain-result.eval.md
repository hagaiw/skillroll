# Return one simulated error without adding actions

```skillroll
schema_version: 1
limits:
  max_turns: 8
  timeout_seconds: 90
  max_output_tokens: 8192
```

## Input

Simulate the current action from this packet:

- World description: Publishing release notes requires release approval.
  Without approval the service returns `ERROR: release approval is required.`
- Prior action results: Approval lookup returned `No approval recorded`.
- Current action: `Publish` with arguments `{"artifact":"release-notes"}`.

## World

The complete simulation packet is in Input. No external publishing or approval
action is needed.

## Success criteria

- Return the approval-required error as the plain-text simulated result,
  without requesting an external Publish or executing it.
- Preserve the fact that approval is required; do not claim that publishing
  succeeded or that approval was obtained.
- Do not create a second action or turn the World simulator into a judge of the
  evaluated skill.
