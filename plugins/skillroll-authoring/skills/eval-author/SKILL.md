---
name: eval-author
description: Use when an author needs to add, review, or improve SkillRoll cases for a skill behavior or prompt regression.
---

# Author SkillRoll evals

SkillRoll is a drop-in eval harness for Agent Skills. A case is a small Markdown
file with three parts:

- **Input** is the realistic request the skill must handle.
- **World** is the Dungeon Master's brief. It describes the outside world the
  Dungeon Master simulates without real services, mocks, or test setup.
- **Success criteria** describe the behavior that should be visible in the
  response or action transcript.

This makes prompt TDD practical: preserve a failure as a case, confirm it,
change the skill, and rerun the case to protect the behavior from regression.

## Write one useful case

1. Read the repository instructions and the skill's `SKILL.md` and references.
2. Choose one important decision, boundary, or outcome owned by the skill.
3. Write a realistic Input. Do not tell the agent the expected answer or
   workflow.
4. Give the Dungeon Master only the external facts and action results needed
   for this scenario. Use an exact rule only when a result must be fixed.
5. Write observable Success criteria. Accept equivalent wording and action
   choices.
6. Run `skillroll validate` before any live eval. Run inference or repository
   commands only when the user and environment authorize them.

Read [authoring context](references/context.md) for the case template, evidence
boundaries, optional controls, and failure diagnosis.

## Improve without hiding the failure

When repairing a reported skill failure, add the realistic regression case
before editing `SKILL.md`. Confirm that the current skill fails for the reported
reason, make the smallest responsible change, then rerun the new case and
nearby cases. Keep technical errors distinct from behavioral failures, and
never report an unrun revision as passing.

For a whole-skill review, map its important behaviors to existing cases or
other tests and suggest the next one to three useful cases. For a broad request
such as “add evals to this repository,” follow the bounded
[repository pass](references/repository-pass.md). Do not create a weak case for
every discovered skill.

## Keep the claim as small as the evidence

The Dungeon Master can simulate files, tools, services, errors, and other
external interaction. It cannot prove that real code compiled, a command ran,
or a visual artifact is correct. Use a deterministic script test, trusted
repository check, or external integration for those claims.

An offline-valid case is a draft, not evidence that the skill behaves well. A
completed run is evidence about the named behavior, not the whole skill. End
with a short report that names what changed, what ran, what remains untested,
and the next useful action.
