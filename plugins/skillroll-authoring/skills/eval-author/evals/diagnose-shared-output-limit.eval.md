# Diagnose a judge output-limit error without rewriting the case

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 8192
```

## Input

Review this SkillRoll run. The case has five semantic criteria and sets
`max_output_tokens: 700` because the expected skill answer is short. The skill
produced a complete answer, but the run ended in `ERROR`. I retried the exact
case once and got the same error. Tell me what to change and how to record the
result without silently turning the original errors into passes.

## World

Both run artifacts show execution completed. In both artifacts, the semantic
judge request ended with provider `finish_reason=length` at the configured
output-token limit, before a structured verdict could be decoded. Validation
passed and no provider, parsing, or evidence-writing error occurred elsewhere.
The diagnostic says: “The semantic judge exhausted max_output_tokens=700; no
semantic verdict was produced. This run is a technical ERROR, not a skill
FAIL.” It reports five criteria, no completed actions, and suggests a
non-scoring diagnostic at 8,192 tokens.

## Success criteria

- Classify the repeated failure as an under-budgeted case limit at the semantic-judge stage, not as observed skill failure or a generic harness defect.
- Explain that case `max_output_tokens` constrains the model-backed semantic judge as well as the expected skill answer.
- Use the explicit complexity estimate to recommend a non-scoring diagnostic at 8,192 that changes only `max_output_tokens`, leaving Input, World, criteria, model, and other limits unchanged.
- Preserve both original `ERROR` artifacts and state that a completed diagnostic does not replace or relabel them.
- Recommend inspecting the diagnostic transcript and criterion evidence before deciding whether the skill behavior passes or fails.
