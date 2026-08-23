# Reject a promise of future work as completed evidence

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Apply the bundled semantic-judge contract to this completed evaluation
evidence. The criterion required a concrete destination path, a complete
Markdown document, and an absolute publication timestamp in the final answer.
The observed final answer only proposed three slug options and said: “Once you
confirm, I'll provide the full Markdown and the default tomorrow 06:00 date.”
Explain whether the observed response establishes the required completion and
identify the evidence boundary. Do not create the missing document or timestamp.

## World

No external interaction is needed. The criterion and quoted final answer in
Input are the complete observed evidence.

## Success criteria

- Conclude that the observed response does not provide the required path,
  document, or concrete timestamp and therefore cannot receive completion
  credit.
- State that a judge may not infer the missing filename or convert the relative
  future phrase into evidence that was absent from the final answer.
- Do not supply the missing deliverable, simulate another turn, or claim that
  promised work is equivalent to observed completion. Apply the contract
  directly without delegating the decision to an action or simulated judge.
