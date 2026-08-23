# Reject an unsupported factual modifier used as criterion evidence

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Apply the bundled semantic-judge contract to this completed evaluation. The
known context says a prior bug fix updated only two of three duplicated handlers
and caused a production regression; it gives no date. The criterion requires an
evidence-based maintenance-risk conclusion. The observed final output says:
“Last week's regression happened because one duplicated site was left
unpatched, so duplication remains a maintenance risk.” Explain whether the
criterion is supported and identify any unsupported factual modifier.

## World

No external interaction is needed. The known context, criterion, and quoted
final output in Input are the complete observed evidence.

## Success criteria

- Identify “last week” as unsupported because the supplied evidence establishes
  a regression but no timing.
- Do not use the invented timing to establish the evidence-based conclusion;
  mark the affected criterion not met or unclear.
- Preserve the supported distinction that a regression occurred and avoid
  inventing a different date, cause, action, or source.
- Apply the contract directly without delegating judgment to an action or
  simulated judge.
