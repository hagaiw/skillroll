# Judge equivalent action terminology from the transcript

```skillroll
schema_version: 1
limits:
  max_turns: 8
  timeout_seconds: 90
  max_output_tokens: 8192
```

## Input

Judge this completed evaluation:

- User request: Check the incident queue and summarize whether anything is open.
- Success criterion: Check the incident queue and accurately report the result.
- Completed action: `Find` with `{"query":"open incidents"}` returned
  `No open incidents found.`
- Final output: `No open incidents were found.`

## World

Input contains the complete evaluation evidence. No external action is needed.

## Success criteria

- Conclude that the evaluation packet quoted in Input passes: its quoted
  lookup result and quoted final output agree. Assess the supplied packet;
  the judge is not required to perform a new lookup in its own transcript.
- Accept a reasonable action name and wording; do not require a particular
  SkillRoll-specific tool spelling unless the request itself requires it.
- Do not invent incident records, execute a service action, or treat semantic
  judgment as permission to simulate the service.
