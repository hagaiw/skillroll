---
name: flow-runner
description: Use when a request needs named skill steps coordinated into one evidence-based result.
---

# Flow runner

Turn the user's named steps into a short execution plan. Request each named
step with the `Skill` action and put its name in the arguments (for example,
`{"name":"summarize-change"}`). Ask each step for its artifact, preserve
which step supplied each fact, and combine only the evidence that was returned.
If a requested step or artifact is missing, say what is missing and stop rather
than inventing it.

Use the [flow context](references/context.md) for the artifact format.
