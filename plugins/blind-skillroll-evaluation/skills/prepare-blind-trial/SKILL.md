---
name: prepare-blind-trial
description: Prepare an isolated external repository trial using an exact target revision and the current local SkillRoll main without running inference.
---

# Prepare a blind trial

Create a disposable workspace from a preregistered target. Pin the target and
the local SkillRoll build to exact commits, record dirty and freshness state,
and install from the selected local SkillRoll checkout rather than silently
substituting a published release.

Initialize SkillRoll around the repository's active skills root, validate the
generated files offline, and add advisory CI only when requested. Do not run
candidate repository commands, overwrite existing workflows, commit, push,
publish, or expose an inference key. Preparation evidence is not a live eval.
The final manifest must name generated paths and commands and explicitly state
whether `doctor` and `eval` ran.

Read [preparation context](references/context.md) for isolation, secrets, and
the trial manifest.

When advisory CI is requested, inspect the generated workflow after creation.
For any secret-backed pull-request step or job, verify an explicit
same-repository guard that excludes fork PRs; do not use `pull_request_target`
to run fork-controlled code with secrets. Report the exact verified guard in
the manifest. A preparation summary that says “verified” without showing the
condition is insufficient. Read the generated file directly if the condition
is missing. If inspection still cannot verify the guard, report a blocker.
For an existing workflow at the destination, report the path collision,
whether the file stayed byte-for-byte unchanged, and whether its own secret
boundary was verified. If only a byte comparison was authorized, report its
secret boundary as unverified.
