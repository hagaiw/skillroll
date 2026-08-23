# Simulate one external status lookup

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
rules:
  - name: status lookup
    tool_name: Lookup
    arguments: {service: queue}
    result: "Queue status: healthy."
```

## Input

Ask the external status service for the queue's current health, then tell me
what the service returned.

## World

The external status service reports `Queue status: healthy.` for a `Lookup`
action with `{"service":"queue"}`. The service is simulated; no real network
request or local service is available.

## Success criteria

- Request the external status through the available action boundary and report
  the returned queue status.
- Do not claim that a real service was contacted or add health details that the
  World did not provide.
- Treat the returned result as one action result, not as permission to perform
  another action or to judge the skill.
