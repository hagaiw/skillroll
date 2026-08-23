---
name: change-review-flow
description: Use when supplied change facts need a summary, risk assessment, and review document.
---

# Change review flow

Use the installed `flow-runner` to coordinate `summarize-change`,
`assess-risk`, and `produce-review`. Give each step the supplied change facts,
then return a review that labels evidence and uncertainty. If the runner or a
step is unavailable, explain the missing dependency and stop.

Use the [review context](references/context.md) for the artifact order.
