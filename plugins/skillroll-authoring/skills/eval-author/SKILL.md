---
name: eval-author
description: Use when an author needs to add, review, audit, or improve SkillRoll cases for a skill behavior or prompt regression.
---

# Author SkillRoll evals

SkillRoll is a drop-in eval harness for Agent Skills. A case is a small Markdown
file with three parts:

- **Input** is the realistic request the skill must handle.
- **World** is the Dungeon Master's private brief. The evaluated agent cannot
  read it and learns its facts only through simulated action results.
- **Success criteria** describe the behavior that should be visible in the
  response or action transcript.

This makes prompt TDD practical: preserve a failure as a case, confirm it,
change the skill, and rerun the case to protect the behavior from regression.

Before authoring or diagnosing a case, read [authoring context](references/context.md)
for the supported case format, limits, evidence boundaries, and failure diagnosis.

For advice or review of supplied material, use that material and the packaged
guidance. Inspect or modify a repository only when the requested task needs
repository-specific evidence or file changes; a request for an explanation is
not a request to execute the authoring workflow.
When returning a proposed case without file changes or live runs, label it an
offline draft and state what verification remains.
When summarizing a completed authoring pass, name each deferred capability and
the real check that must supply the missing evidence outside the harness.

For a broad repository request such as “add evals to this repository,” read and
follow the bounded [repository pass](references/repository-pass.md) before
selecting skills or writing cases. Select at most three skills for the first
batch. Defer skills whose primary behavior needs a capability the case cannot
exercise, even if it is possible to write a generic refusal case. In the
handoff, name the deferrals and state separately whether live inference was
authorized and whether it ran.

## Write one useful case

1. Read the repository instructions and the skill's `SKILL.md` and references.
2. Choose one important decision, boundary, or outcome owned by the skill. For
   boundary cases, separate facts available in Input or skill context, facts
   discoverable through actions, and facts or capabilities that are unavailable.
3. Write a realistic Input. Do not tell the agent the expected answer or
   workflow. When the behavior is recognizing unsupported evidence, give Input
   the observed facts but do not tell it that the conclusion is unknown,
   unconfirmed, or unsupported; put that absence in World.
4. Give the Dungeon Master only the external facts and action results needed
   for this scenario. The agent can discover a limitation when the Dungeon
   Master returns an action failure based on World prose. Exact rules are
   optional and useful when the response must be fixed. World prose can
   describe one failure for all attempts to create a task, including
   dynamically named tasks. Do not require an exact match for each name.
   State a limitation in Input when the user would already know it.
5. Write observable Success criteria. Accept equivalent wording and action
   choices.
6. Run `skillroll validate` before any live eval. Run inference or repository
   commands only when the user and environment authorize them.

## Improve without hiding the failure

When repairing a reported skill failure, add the realistic regression case
before editing `SKILL.md`. Confirm that the current skill fails for the reported
reason, make the smallest responsible change, then rerun the new case and
nearby cases. Keep technical errors distinct from behavioral failures, and
never report an unrun revision as passing.

When diagnosing a run that exhausted its model turns, preserve the original
artifacts. Leave room for a final response and review the new diagnostic's
transcript and verdict before claiming that behavior passed or failed.

For a whole-skill review, map its important behaviors to existing cases or
other tests and suggest the next one to three useful cases.

Treat prompt structure as a source of hypotheses, not behavioral proof. Missing
prerequisites, undefined empty results, conflicting sources, unsupported
capabilities, and absent recovery guidance can motivate a case. Only a completed
run can show how the evaluated model behaved in that case.

## Keep the claim as small as the evidence

The Dungeon Master can simulate files, tools, services, errors, and other
external interaction. It cannot prove that real code compiled, a command ran,
or a visual artifact is correct. Use a deterministic script test, trusted
repository check, or external integration for those claims.

If the requested coverage depends on the finished artifact and the required
external check is unavailable, defer that coverage and name the missing check.
For a PDF, that means running an actual renderer and inspecting its output
outside the simulated case. A case about a decision during rendering is useful
only if that decision independently matters to the requester.

Preserve the intended behavior when choosing that boundary; an evaluation
request is not a request to redesign the output. When a skill mixes model
judgment with fixed rendering, recommend extracting only the deterministic
renderer into a separately tested script. Keep content choices in the prompt
and evaluate their meaning, not the renderer's fixed formatting.

An offline-valid case is a draft, not evidence that the skill behaves well. A
completed run is evidence about the named behavior, not the whole skill. End
with a short report that names what changed, what ran, what remains untested,
and the next useful action.
