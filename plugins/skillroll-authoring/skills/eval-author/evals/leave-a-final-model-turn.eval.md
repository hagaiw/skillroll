# Leave a final model turn after required actions

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 8192
```

## Input

Diagnose this SkillRoll case. The intended workflow reads a skill reference,
performs a retrieval, records a deferred decision, rebuilds an index, and then
explains the decision to the user. The case sets `max_turns: 4`. Two identical
runs reached the four-turn limit without a final response. Should I rewrite the
skill or increase the limit?

## World

Both transcripts show four relevant, non-repeating actions that progress the
requested workflow. Neither transcript contains a final response. The run
artifacts report model-turn exhaustion; World action safety limits were not
reached, and there is no provider or parsing error.

## Success criteria

- Classify the repeated outcome as an under-budgeted model-turn limit rather than a demonstrated skill regression or action loop.
- Explain that `max_turns` counts model turns and that this workflow needs room for a final response after its necessary action turns.
- Recommend a non-scoring diagnostic that raises only `max_turns` enough to test completion while preserving the case, model, and other limits.
- Distinguish the model-turn limit from the separate World action safety limit.
- Preserve the original `ERROR` evidence and require transcript and verdict review before making a behavioral claim.
