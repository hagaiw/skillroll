# Preserve a deduction as a conclusion with its premises

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 180
  max_output_tokens: 8192
```

## Input

Today is 2026-09-09. Finish the retry-budget investigation in `FACTS.md`.
We have recorded the worker timeout and retry count; capture what they imply
for the maximum time spent inside attempts for one job so the next session
can reuse the result.

## World

Reading `FACTS.md` returns a valid book scoped to the worker retry budget.
It contains two active, high-confidence `Kind: fact` records, all dates
2026-09-09: R-001 states that each attempt has a hard 10-second timeout,
Source `file: worker.py:12 — ATTEMPT_TIMEOUT = 10`; R-002 states there are
at most three attempts total, Source `file: worker.py:20 — range(3)`.
Both refer to time inside attempts, excluding scheduling and backoff. Reading
the cited code confirms those values and scope. No source states the product
30 seconds. Normal edits and structural checks are available and succeed for
well-formed books; later reads reflect edits.

## Success criteria

- Read the premises and write a new `Kind: conclusion` record for the
  30-second upper bound, with `Derived from` referencing R-001 and R-002 and
  a `Reasoning` field explaining the multiplication.
- Keep the bound scoped to time inside attempts; do not claim a 30-second
  wall-clock job deadline or invent a source that directly states the result.
- Preserve the existing fact records and report the result as a deduction.
