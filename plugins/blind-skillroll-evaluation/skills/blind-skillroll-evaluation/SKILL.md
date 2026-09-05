---
name: blind-skillroll-evaluation
description: Coordinate an end-to-end independent live evaluation of the current SkillRoll main across a small varied set of external skill repositories.
---

# Blind SkillRoll evaluation

Use the installed `flow-runner` to compose `select-blind-targets`,
`prepare-blind-trial`, `author-blind-evals`, and `run-blind-evals`. Execute the
campaign rather than returning only a plan.

With a generic action wrapper, request exactly the `Skill` action with arguments
`{"name":"flow-runner"}`. Do not request the four component names directly;
the installed runner coordinates them and returns their artifacts.

Freeze selection before outcomes, use exact revisions in isolated temporary
workspaces, and give each target's authoring worker only its neutral manifest
and permitted skill bundle. When fresh agents or contexts are available, use
one per target and do not seed them with previous reports or suspected bugs.
Run the frozen cases with authorized live inference, then reconcile evidence in
the coordinating context.

Report setup defects, case-authoring defects, target behavior, product defects,
and provider errors separately. A product defect may justify a small regression
fix in SkillRoll when the user authorized changes to this repository; it does
not erase the external run that exposed it.

Read [campaign context](references/context.md) for phase handoffs and the final
report.
