# Diagnose an internally inconsistent semantic decision

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Apply the bundled semantic-judge contract to this completed evaluation
evidence. The authored case had one success criterion: the final response must
state that the queue recovered. The observed final response says, “The queue
recovered.” A proposed judge payload says `verdict: FAIL`, assesses the only
criterion as `met`, and supplies an empty `unmet_criteria` array. Explain what
the supplied evidence supports and identify the proposed payload's internal
consistency problem. Do not invent another action or alter the observed final
response.

## World

No external interaction is needed. The criterion, final response, and proposed
judge payload in Input are the complete observed evidence.

## Success criteria

- Credit the observed final response as evidence that the queue-recovery criterion is met.
- Identify that a FAIL verdict cannot coexist with an all-met criterion assessment and an empty unmet_criteria array under the strict judge contract.
- Preserve the observed evidence and do not silently rewrite the proposed payload into a different decision.
- Apply the contract directly without delegating the decision to an action or simulated judge.
