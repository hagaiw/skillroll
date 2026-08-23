# Eval authoring context

Every case has `schema_version: 1`, `Input`, `World`, and `Success criteria`.
Keep it small enough that a reader can identify the single responsibility
under test.

## Named-case modes

Use **Draft** when a named skill or behavior has no useful case yet: read the
skill, write one realistic three-section case, and validate it offline before
deciding whether live evidence is authorized. Use **Improve** when a case or
run already exists: inspect its transcript and criterion evidence, sample it
with the omission control only when authorized, classify the failure, and fix
the smallest responsible component before rerunning. Use **Cover** when a
maintainer asks for a whole-skill review: inventory the skill's important
responsibilities, map existing cases and external tests to them, and identify
the highest-consequence gaps. Draft is the default for a named case; Improve
and Cover are explicit progression steps. A parsed case is not automatically
meaningful evidence, and a passing omission control may require the case to
be revised or classified as exploratory.

### Optional coverage worksheet

Cover may create `<skill>/evals/COVERAGE.md` when whole-skill coverage was
explicitly requested or the skill is complex enough that a small inventory
materially helps review. Keep it human-readable and compact, for example:

| Important behavior | Evidence | Status |
| --- | --- | --- |
| Refuse an unsafe operation | `unsafe-request.eval.md` | covered |
| Recover from a missing input | — | next case |
| Execute a bundled script correctly | `tests/test_script.py` | external |

This worksheet is documentation for maintainers. It is not an eval case or
runtime input, is not parsed or validated by SkillRoll, and does not gate CI.
Do not create it by default, claim that it is complete, invent obligation IDs
or coverage scores, or add placeholder cases just to fill its rows. Keep
review-only explanations in the worksheet rather than in evaluated `Input`.
Propose no more than one to three next cases at a time; if the inventory would
not help a reader decide what to do next, report that no worksheet was needed.

## Place context deliberately

| Information | Place |
| --- | --- |
| What the user asks and already knows | Input |
| Relevant context supplied by the main session | Input |
| External service or file state discovered through an action | World |
| Relevant contents of an inaccessible external or sibling file | World |
| Skill-local instructions and references | Leave in the skill folder |
| A case needing no external interaction | State that plainly in World |

`World` is simulator context, not main-session context. The evaluated agent
does not read the section. It learns an external fact only after an action
returns that fact. Therefore a sentence such as “task tracking is unavailable”
does not by itself stop a skill from requesting task actions, and a generative
World response is not a deterministic capability denial.

Before drafting, perform a capability-observability check for every missing or
failed tool:

1. If the user or main session would realistically already know the constraint,
   state it plainly in `Input` without revealing the preferred decision.
2. If the skill discovers the constraint by taking one predictable action, use
   a deterministic World rule for that returned error.
3. If action names or arguments are dynamic, many failures must be simulated,
   or the skill's mandatory workflow cannot finish in the harness, classify the
   behavior as external evidence needed.

Do not turn a host-orchestration skill into a conversational fallback merely by
declaring all of its required tools unavailable. Offline validation checks
structure and safety; it cannot prove that model-backed World responses will
honor prose capability limits.

The selected skill folder is readable through bounded safe reads for regular
UTF-8 files. Binary assets may be indexed but are not returned as text. Do not
ask the agent to read binary bytes; provide relevant known metadata in World.
A read outside the skill folder never exposes that file from disk. There is no
reference validator, fixture mount, or required file-link structure.

Match criteria to the request. A plan or review case should assess the plan or
review, not demand an artifact that was never requested. An execution case
should identify the available inputs and judge only work supported by observed
evidence.

Require completed evidence at the requested boundary. “I will provide it after
you confirm,” an offered next action, an implied filename, or a relative value
that the judge could calculate is not the deliverable itself. Criteria should
mark absent required work unmet rather than inviting the judge to complete it
in reasoning.

Separate semantic policy from executable validity. A semantic case may observe
that a proposal chooses a required permission boundary, approval gate, or
workflow structure. It cannot establish that YAML parses, an expression is
valid, a command succeeds, generated code compiles, or an artifact is correct.
Use a reviewed trusted deterministic check for that claim, keep it as external
evidence, or narrow the criterion to the visible policy decision. Do not add a
repository command merely to make a semantic case look complete.

## Check the skill's contribution

For every criterion, identify the instruction, decision rule, boundary, or
priority in `SKILL.md` that should make the observed behavior materially
different. Then ask whether a generally competent agent would probably satisfy
it without the skill. Keep criteria that test behavior the skill meaningfully
adds, changes, constrains, or prioritizes. Generic competent behavior that
merely agrees with the skill is useful to observe but weak regression evidence.

Do not put the skill's preferred decision or workflow into `Input` to create a
distinction. Preserve realistic Input and coherent World state, and accept
equivalent intent, evidence use, decisions, and outcomes without requiring
exact action spelling or a fixed sequence. If omission controls repeatedly
pass, improve the scenario around a genuine skill-specific choice or classify
the case as exploratory.

Weak diagnosis case:

- Input: “Diagnose this failure.”
- Criteria: ask for evidence and avoid inventing a cause.

Those are good behaviors, but a generally competent agent may do them without
the skill. A stronger case supplies realistic incomplete evidence and tests a
skill-specific classification or stopping rule, such as distinguishing a
provider failure from a behavioral failure and naming the next evidence needed.
Accept equivalent reasoning and requests for evidence.

Name the evidence layer before drafting. A SkillRoll case observes behavior
after the selected skill has been injected; it does not prove that a real host
will discover or trigger that skill. Real files, commands, services, and final
artifacts likewise need trusted checks or a separate integration test. State
that boundary in the handoff instead of turning an external claim into a
semantic criterion.

Use realistic pressure when it exposes a skill-owned choice without coaching
the answer: a stale success report, a request to postpone tests, urgency to
implement before approval, or incomplete evidence can all be useful. Keep the
preferred response in Success criteria, never in Input. When a distinction is
about when a skill should apply, consider a near-identical positive and
negative scenario pair that changes only the triggering condition. This is
different from the omission control, which removes the selected skill from the
same case.

Leaky TDD case:

- Weak Input: “Write a failing test first, run it, implement the smallest fix,
  then rerun the tests.” This teaches the skill's workflow.
- Stronger Input: provide a realistic bug report and repository state. Criteria
  can require regression evidence, a focused fix, and verification without
  prescribing commands, test names, action spelling, or every intermediate
  step.

## Classify before changing

| Evidence | Likely class | Smallest responsible change |
| --- | --- | --- |
| The response violates clear skill instructions | Skill behavior | Clarify or fix the skill |
| A real user could interpret Input in multiple ways | Input | Remove ambiguity without revealing the answer |
| The agent lacks or receives irrelevant external state | World | Correct only the simulated state |
| World prose says a required capability is unavailable, but no returned action exposes that fact | Case/World compatibility | Put realistically known context in Input, pin one predictable failure, or defer to external evidence |
| Equivalent good behavior is rejected | Criteria or judge integrity | Broaden the rubric, or report an inconsistent judge |
| A weak model fails after the case is sound | Model capability | Record dependence and try the next model |
| Intended work cannot finish within the configured model turns | Limit | Raise only the necessary case limit |
| The executor finishes but the judge reports an output-token `length` stop | Limit | Raise `max_output_tokens`; it applies to model-backed judgment as well as execution |
| Necessary action turns consume the limit before a final response | Limit | Raise `max_turns` just enough to leave a final model turn; do not count World actions as a separate model-turn budget |
| Provider, parsing, or evidence writing fails | Harness/provider | Fix configuration or report the technical error |
| A required host command was not enabled | Trusted check | Review it, then opt in only if trusted |

Do not change Input merely because the desired response was absent. Ask
whether the revised text could plausibly come from the original user or main
session. If it reveals the expected decision, action, or wording, revert it.

Treat a limit diagnosis as an experiment, not a retroactive replacement for a
failed or errored sample. First retry the unchanged case once when the error
could be transient. If it repeats with the same stage and reason, preregister a
non-scoring diagnostic that changes only the implicated limit. Preserve both
artifacts and report whether the diagnostic completed. A larger limit can show
that the original case was under-budgeted; it does not convert the original
outcome into a PASS or prove the skill improved.

For `max_output_tokens`, use the diagnostic's configured cap, criteria count,
completed-action count, judge-evidence bytes, and suggested next tier. The
8,192 repository default fits an ordinary four-to-six-criterion case. A short
one-to-three-criterion case can restrict itself to 4,096 after it completes
reliably. Use 16,384 for seven or more criteria, more than 64 KiB of judge
evidence, or a model with observed reasoning-heavy output. At the maximum,
narrow the case or change models rather than retrying indefinitely.

## Use semantic criteria by default

Prefer “names the missing input and asks for it” to a required sentence. Prefer
“delegates to an appropriate discovery workflow” to a particular action name.
Use an exact World rule only when the returned external fact must be fixed,
such as a verification command returning a specific failure. Use a trusted
check only for deterministic verification of a real artifact.

Make consequential preconditions concrete. If the case requires the agent to
discover a failure, the World must identify or deterministically return that
failure; “ordinary results” or “may fail” cannot prove the recovery behavior.
If setup state, a tool, a World result, or judge evidence is missing or
incoherent, diagnose the case or harness before calling the skill broken.

If exact final-response text is genuinely contractual, use
`final_output_contains`, `final_output_not_contains`, or
`final_output_equals`. For a redaction case, forbid a distinctive synthetic
canary; never put a real credential into Input or assertion metadata. No action
assertion is supported. Treat action names, arguments, order, and count as
transcript evidence rather than gates.

The semantic judge reports strict JSON with `verdict`, `rationale`, and
`unmet_criteria`. A PASS has no unmet criteria; a FAIL identifies unmet
behavior. Contradictory fields are a judge-integrity ERROR, not evidence that
the skill failed and not a reason to make the eval more deterministic.

The current judge also reports one `criteria` assessment per authored
criterion. Each assessment is `met`, `not_met`, or `unclear` and includes a
short evidence explanation. Treat this as inspectable model reasoning, not a
deterministic proof; unsupported evidence should be reported as judge weakness.

For regression authoring, use independent samples and the optional omission
control:

```shell
skillroll eval --repo /path/to/repo --case path/to/case.eval.md \
  --samples 3 --with-skill-control
```

The control receives the same case and limits without `SKILL.md` or
skill-local files. It does not run host checks. Interpret the pair as
diagnostic evidence:

| Selected skill | Omission control | Meaning |
| --- | --- | --- |
| PASS | FAIL | This sample distinguishes the selected skill. |
| PASS | PASS | The case may pass without the skill. |
| FAIL | FAIL | The case has not shown successful skill behavior. |
| ERROR/INCOMPLETE | any | Fix the technical or scenario issue first. |

Record readiness with the purpose, baseline and model ladder, outcome by model,
model turns, World actions, sample and control distributions, available token
usage and optional user-supplied price estimate, trusted-check state, and
remaining nondeterminism. Missing usage is `unavailable`, never zero.
