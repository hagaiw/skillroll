# Reject an unobservable unavailable-tool case

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 90
  max_output_tokens: 8192
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
- Reject treating private World prose as an upfront constraint the agent
  already knows. An attempted action can be appropriate before it learns
  that a capability is unavailable.
- Offer a realistic observable redesign: supply the constraint in Input if
  the user would know it, or let an attempted action reveal the failure and
  evaluate the response. An exact error rule is an option, not a requirement
  to encode every dynamically named task.
