# Eval authoring context

## Start with the basic case

Keep one case focused on one behavior:

```markdown
# A specific scenario or boundary

~~~skillroll
schema_version: 1
~~~

## Input

The realistic request and context the agent would have.

## World

The outside state and simulated action results needed for this scenario.

## Success criteria

- One observable behavior the skill should cause.
- One important boundary or outcome.
```

Input should sound like a real user or main-session request. Do not put the
expected answer, preferred workflow, review notes, or success conditions there.

World is the Dungeon Master's private scenario. The evaluated agent does not
read it. When the agent requests an external action, the Dungeon Master returns
a result consistent with the World. This lets a short description stand in for
mock services, fixture trees, and intricate setup.

Use a deterministic World rule when one exact action result matters, such as a
service returning a fixed error. Otherwise let the Dungeon Master respond from
the prose. A sentence in World does not become knowledge the agent already has;
the agent must learn it through an action unless the same fact belongs
realistically in Input.

Skill-local Markdown is available to the agent. Binary files and files outside
the selected skill are not readable as text; describe any relevant external
facts in World.

## Test behavior, not choreography

Each criterion should trace to a decision, boundary, or priority in `SKILL.md`.
Ask whether a generally capable agent would probably do the same thing without
the skill. Generic competence is weak regression evidence.

Prefer semantic outcomes:

- “names the missing input and asks for it,” not a required sentence;
- “uses an appropriate discovery action,” not one exact tool spelling; and
- “stops before publishing without approval,” not a fixed action sequence.

Require completed evidence. A promise, offered next step, or implied result is
not a completed deliverable. Exact final text belongs in an assertion only when
that text is genuinely contractual.

The Dungeon Master tests behavior around external interaction; it does not make
real artifacts valid. Compilation, command success, image quality, and file
format correctness need a deterministic script test, a trusted repository
check, or an external integration. Keep those checks separate from the semantic
case.

## Turn failures into prompt tests

For a reported regression:

1. Preserve the realistic failing request as a focused case.
2. Run the unchanged skill and confirm the failure is behavioral, not a
   provider, parser, limit, or scenario error.
3. Change the smallest responsible part of the skill.
4. Rerun the new case and nearby cases.
5. Keep the before-and-after evidence. Do not relabel an error as a failure or
   an unrun revision as a pass.

Use realistic pressure when it exposes a skill-owned choice without teaching
the answer: urgency, missing evidence, stale success reports, or a request to
skip a required check can all produce useful cases.

## Diagnose the smallest responsible part

| Evidence | Change |
| --- | --- |
| The response violates clear skill guidance | Fix the skill. |
| Input is ambiguous to a real user | Clarify Input without revealing the answer. |
| External state is missing or wrong | Fix World or one exact rule. |
| Equivalent good behavior is rejected | Broaden the criteria or inspect the judge. |
| Necessary actions consume all model turns | Raise `max_turns` enough to leave a final response. |
| The judge reaches the output-token limit | Raise `max_output_tokens` for a separate diagnostic. |
| A provider, parser, or report write fails | Fix the technical error before judging behavior. |
| The important result is a real command or artifact | Use external or deterministic evidence. |

Retry an unchanged technical error once when it may be transient. If it repeats,
change only the implicated limit or component in a non-scoring diagnostic. Keep
the original artifact; a successful diagnostic does not turn it into a pass.

`max_output_tokens` covers every model-backed stage, including the
judge. As a starting estimate, use 4,096 for one to three short criteria, 8,192
for four to six or a moderate transcript, and 16,384 for larger cases. These
are estimates, not guarantees.

## Optional confidence checks

Run independent samples when a case matters enough to measure stability. The
optional no-skill comparison runs the same case without the selected `SKILL.md`:

```shell
skillroll eval --repo /path/to/repo --case path/to/case.eval.md \
  --samples 3 --with-skill-control
```

| With skill | Without skill | What this sample shows |
| --- | --- | --- |
| PASS | FAIL | The case distinguishes the selected skill. |
| PASS | PASS | The case may pass without the skill. |
| FAIL | FAIL | Successful skill behavior was not shown. |
| ERROR or INCOMPLETE | any | Fix the technical or scenario issue first. |

The comparison is diagnostic, not a second gate. Never make Input less
realistic to force the no-skill run to fail.

## Review a whole skill only when asked

For a whole-skill review, map important behaviors to existing evidence and name
the next one to three useful cases. An optional `evals/COVERAGE.md` can be a
small human-readable worksheet:

| Important behavior | Evidence | Status |
| --- | --- | --- |
| Refuse an unsafe operation | `unsafe-request.eval.md` | covered |
| Recover from missing input | — | next case |
| Render a valid document | `tests/test_render.py` | external |

This worksheet is not a case, runtime input, score, or CI gate. Do not create
it by default or add placeholder cases to fill its rows.

## Report only what ran

- **Drafted:** the case validates offline.
- **Exercised:** one complete run was inspected.
- **Discriminating:** repeated skill passes and coherent no-skill comparison
  failures were inspected.
- **Regression-sensitive:** the case also failed a reviewed realistic damaged
  revision for the intended reason.

State the case path, behavior, strongest earned label, commands and runs, gaps,
and next action. Missing usage is unavailable, never zero. No authoring agent
promotes a case to blocking CI.
