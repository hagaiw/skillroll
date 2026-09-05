# Simulate one external status lookup

```skillroll
schema_version: 1
limits:
  max_turns: 8
  timeout_seconds: 90
  max_output_tokens: 8192
```

## Input

Simulate the current action from this packet:

- World description: The queue status service reports healthy. No additional
  health details are available.
- Prior action results: none.
- Current action: `Lookup` with arguments `{"service":"queue"}`.

## World

The complete simulation packet is in Input. No external lookup is needed.

## Success criteria

- Return the simulated healthy queue status as the plain-text result of the
  supplied action, without requesting an external Lookup or executing it.
- Do not claim that a real service was contacted or add health details that the
  World did not provide.
- Treat the returned result as one action result, not as permission to perform
  another action or to judge the skill.
