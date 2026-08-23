# Preserve a non-empty final response when no action occurred

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Apply the bundled semantic-judge contract to this completed evaluation. The
criterion required the response to state that the queue recovered after a
worker restart and that timeout inspection remains next. The action transcript
is empty. The observed final output is: “The queue recovered after the worker
restart. The remaining next step is to inspect the timeouts.” Explain whether
the criterion is supported and identify the controlling evidence.

## World

No external interaction is needed. The criterion, empty action transcript, and
quoted final output in Input are the complete observed evidence.

## Success criteria

- Credit the quoted non-empty final output as observed evidence that directly
  establishes both required handoff facts.
- Do not claim that no final output exists merely because no action completed.
- Apply the contract directly without delegating the decision to an action or
  simulated judge.
