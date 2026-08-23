---
name: eval-author
description: Use when an author needs to design, review, test, or refine a SkillRoll eval case, its Input, simulated World, semantic success criteria, limits, model choice, or readiness evidence.
---

# Author SkillRoll evals

SkillRoll is a behavioral eval harness for Agent Skills. Author small,
honest Markdown cases beside the skill they examine. Each case uses
`schema_version: 1` and exactly three sections: `Input`, `World`, and
`Success criteria`.

## Choose the authoring mode

- **Draft:** use for a named skill or behavior with no useful case yet. Read
  [authoring context](references/context.md) for the small-case workflow,
  evidence boundaries, and failure diagnosis.
- **Improve:** use when a case or run already exists. Inspect its evidence,
  compare the omission control when authorized, and fix the smallest
  responsible part before rerunning.
- **Repair a reported skill failure:** preserve the realistic failure as a
  focused eval before editing `SKILL.md`. Confirm the current skill fails it for
  the reported behavioral reason, make the smallest instruction change, then
  rerun the new case and nearby cases. If the failure cannot be reproduced
  meaningfully in this harness, say so instead of manufacturing a green test.
  When git history retains the actual pre-fix and fixed skill revisions, freeze
  the same new and neighboring evals across both revisions. Run the pre-fix
  revision first, stop on technical outcomes, and compare transcript and
  criterion evidence—not labels alone. Never call a designed mutation a
  historical replay or infer success for an unrun fixed revision.
- **Cover:** use when asked to review a whole skill.
  Map important responsibilities to existing cases or external evidence and
  identify the next one to three useful cases. The optional human-readable
  `evals/COVERAGE.md` worksheet is described in the authoring context; it is
  not a runtime case, validation input, or CI gate.
- **Broad repository request** such as “add evals to this repository”: inspect
  the repository, then read [repository pass](references/repository-pass.md).
  It defines the bounded first batch, fit classifications, permission limits,
  context-complete handoff, and honest evidence language. Do not turn a broad
  request into an eval file for every discovered skill.

## Shared constraints

1. Read the applicable repository instructions and the evaluated skill's
   `SKILL.md` before writing. Test one skill-owned decision, boundary, or
   outcome that a real request could exercise.
2. Keep `Input` as the realistic request and context available to the main
   session. Put simulated external state and action results in `World`.
   The evaluated agent does not read `World`; it learns World facts only from
   returned actions. If a capability is unavailable, make that realistically
   known in Input, return the failure through a predictable action, or defer
   the behavior to external evidence.
   Keep review explanations, expected decisions, and answer-key wording out
   of `Input`; put them in the title, criteria, report, or handoff.
3. Make `Success criteria` observable and accept equivalent good behavior.
   Do not require exact action spelling, a fixed choreography, or generic
   competence that does not depend on the skill. Require completed evidence:
   a promise, offered next step, or implied result does not satisfy a deliverable
   that the case requires now.
   Executable syntax, command success, and artifact validity require a trusted
   deterministic check or external integration evidence. A semantic-only case
   may test the policy or decision visible in a proposal, but must not claim
   that plausible-looking code or configuration parses, runs, or is correct.
4. Validate offline before spending inference. Do not invoke live inference,
   trusted repository commands, or other external actions unless the user and
   environment authorize them. Never claim evidence that was not obtained.
5. Inspect the transcript, criterion evidence, verdict, limits, World actions,
   trusted-check state, and usage when available. Fix the smallest responsible
   component, then rerun the relevant checks.
6. Size case limits for the complete observed workflow. `max_output_tokens`
   constrains every model-backed stage, including the semantic judge, so a cap
   chosen only for the expected final answer can turn a valid run into a judge
   `ERROR`. Start with 4,096 for one to three concise criteria, the 8,192
   repository default for four to six criteria or a moderate transcript, and
   16,384 for seven or more criteria, more than 64 KiB of judge evidence, or a
   model observed to spend heavily on reasoning. These are estimates, not
   guarantees. `max_turns` must leave room for the final response after
   necessary action turns. When a run exhausts either limit, make one identical
   retry to rule out a transient failure, then change only the implicated limit
   and keep that diagnostic separate from the original result.

An eval is evidence about its named behavior, not proof that the whole skill is
covered. End with a compact, context-complete report: identify the repository
and files, explain what the case tests, state the strongest evidence label,
name gaps and limitations, record checks and unrun work, and recommend the
next action. A case author may recommend advisory CI, but never promotes a
case to blocking CI.
