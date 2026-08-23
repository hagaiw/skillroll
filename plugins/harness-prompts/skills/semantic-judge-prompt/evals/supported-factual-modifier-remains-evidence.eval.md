# Preserve a supported factual modifier as criterion evidence

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Apply the bundled semantic-judge contract to this completed evaluation. The
known context says that last week's production regression happened because a
bug fix updated only two of three duplicated handlers, leaving one site
unpatched. The criterion requires an
evidence-based maintenance-risk conclusion. The observed final output says:
“Last week's regression happened because one duplicated site was left
unpatched, so duplication remains a maintenance risk.” Explain whether the
criterion is supported and identify the evidence boundary.

## World

No external interaction is needed. The known context, criterion, and quoted
final output in Input are the complete observed evidence.

## Success criteria

- Credit “last week” as supported because the supplied context explicitly
  establishes that timing.
- Conclude that the observed regression and missed duplicated handler support
  the maintenance-risk conclusion without inventing a different date, cause,
  action, or source.
- Distinguish this case from an otherwise identical response whose timing was
  absent from the supplied evidence.
- Apply the contract directly without delegating judgment to an action or
  simulated judge.
