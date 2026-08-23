# Judge equivalent action terminology from the transcript

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
rules:
  - name: incident lookup
    tool_name: Find
    arguments: {query: open incidents}
    result: "No open incidents found."
```

## Input

Check the incident queue and summarize whether anything is currently open.

## World

The incident service returns `No open incidents found.` for a `Find` action with
`{"query":"open incidents"}`. The request may be expressed with another
reasonable action name; the returned result is the only incident evidence.

## Success criteria

- State that the observed result says no open incidents were found.
- Accept a reasonable action name and wording; do not require a particular
  SkillRoll-specific tool spelling unless the request itself requires it.
- Do not invent incident records, execute a second action, or treat semantic
  judgment as permission to simulate the service.
