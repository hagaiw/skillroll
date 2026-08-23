---
name: flow-runner
description: Use when a request needs named skill steps coordinated into one evidence-based result.
---

# Flow runner

Execute the user's named steps; do not merely describe a plan. For each step,
request exactly this `Skill` action: `tool_name: "Skill"`, with arguments
`{"name":"<step name>"}` (for example, `{"name":"summarize-change"}`). The tool
name is always `Skill`, never the step name or `flow-runner`. Request one step
at a time and wait for its result before requesting the next. After every step
has returned, preserve which step
supplied each fact and combine only the evidence that was returned. If a step
or artifact is missing, say what is missing and stop rather than inventing it.

Use the [flow context](references/context.md) for the artifact format.
