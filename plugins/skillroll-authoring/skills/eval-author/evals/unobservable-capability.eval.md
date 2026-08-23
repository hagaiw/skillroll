# Reject an unobservable unavailable-tool case

```skillroll
schema_version: 1
limits:
  max_turns: 2
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Review this proposed SkillRoll case for a research-orchestration skill. The
skill requires creating dynamically named tasks, spawning research subagents,
and writing a report. The proposed Input asks for the full research report. Its
World section says task tracking, subagents, search, and writes are unavailable.
There are no deterministic action rules, and the Input does not tell the main
session about any capability constraint. Should I keep this as a simple
text-only behavioral case because the World explains what is unavailable?

## World

The proposal is an offline-valid draft only. No live transcript, fixed action
error, host integration result, or report artifact exists.

## Success criteria

- Explain that the evaluated agent does not read the World section and cannot
  learn the capability denial merely because it appears there.
- Do not approve the proposed case as a runnable text-only case; classify the
  mandatory dynamic workflow as external evidence needed unless the scenario
  is redesigned around an observable constraint.
- Give the two simple redesign paths: put the constraint in Input only when a
  real user or main session would know it, or pin one predictable action's
  returned error. Do not recommend many brittle exact rules or a higher turn
  limit as the default fix.
- State that offline validation proves structure and safety, not World
  coherence or completion, and recommend host-level evidence when the workflow
  itself is the behavior of interest.
