---
name: flow-runner
description: Use when a request needs named skill steps coordinated into one evidence-based result.
---

# Flow runner

Execute the user's named steps; do not merely describe a plan. Request each
step separately with the `Skill` action and put its name in the arguments (for
example, `{"name":"summarize-change"}`). Never request `flow-runner` as an
action and never batch the steps into one action. After every requested step
has returned, preserve which step supplied each fact and combine only the
evidence that was returned. If a requested step or artifact is missing, say
what is missing and stop rather than inventing it.

Use the [flow context](references/context.md) for the artifact format.
