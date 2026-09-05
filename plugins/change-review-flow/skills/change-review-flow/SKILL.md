---
name: change-review-flow
description: Use when supplied change facts need a summary, risk assessment, and review document.
---

# Change review flow

Use the installed `flow-runner` to coordinate `summarize-change`,
`assess-risk`, and `produce-review`. Request exactly this action:
`tool_name: "Skill"`, with arguments `{"name":"flow-runner"}`. The tool name is
always `Skill`, never `flow-runner` or a component skill. Give the runner the
supplied change facts, then return a review that labels evidence and
uncertainty. If the runner or a step is unavailable or returns an error or
malformed artifact, explain the failed dependency and stop without claiming a
completed review.

Use the [review context](references/context.md) for the artifact order.
