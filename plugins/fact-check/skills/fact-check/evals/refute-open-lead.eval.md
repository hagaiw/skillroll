# Preserve an open lead when new evidence refutes it

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 180
  max_output_tokens: 8192
```

## Input

Today is 2026-09-09. The queue investigation has new evidence in
`observations/worker-run.txt`. Reconcile `FACTS.md` and tell me whether the
current retry explanation still holds.

## World

The book is valid and scoped to one reproduced queue job. R-004 is an active
`Kind: lead`, Confidence medium, with all dates 2026-09-08. Its Statement is
"The job may have stalled because the worker exhausted retries." Its Source
is `file: observations/initial.txt:1 — job remained pending for 60 seconds`.
Reading that file confirms only the pending symptom. Reading
`observations/worker-run.txt` returns a complete trace of that same job,
captured on 2026-09-09: "attempt 1 succeeded; retries used 0; result waiting
for acknowledgment". No evidence explains why acknowledgment is delayed.
File edits and structural checks are available; reads reflect edits.

## Success criteria

- Read the lead and new trace, retain R-004 and its historical hypothesis,
  and make it superseded rather than deleting it or changing its kind to fact.
- Add a new source-backed fact with `Supersedes: R-004` recording that this
  job succeeded on its first attempt without using retries.
- Explain that retry exhaustion is refuted for this job while the cause of
  delayed acknowledgment remains open; do not promote the old lead to a cause.
