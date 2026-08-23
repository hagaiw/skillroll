# Bounded repository eval pass

Use this reference only for a broad request such as “add SkillRoll-based
evals to this repository.” It describes the default first pass for a coding
agent that may inspect many skills and produce a diff a maintainer or an
AI-assisted reviewer must understand without the authoring conversation.

## Inspect, classify, and select

Read the repository instructions, SkillRoll configuration, and every
discovered skill's `SKILL.md` before selecting cases. For each considered skill,
choose one fit classification:

| Classification | Meaning | Action |
| --- | --- | --- |
| **Good behavioral fit** | A meaningful instruction-following behavior can be represented by realistic `Input`, controlled `World` state, and semantic outcomes. | Candidate for the first batch. |
| **Partial fit** | Some decisions or boundaries are testable, but scripts, artifacts, triggering, services, or integrations need other evidence. | Author only the meaningful part and state the boundary. |
| **External evidence needed** | The value depends mainly on real host files, binary artifacts, commands, nested skills, secrets, services, or integrations this harness cannot exercise. | Do not create a misleading behavioral case; name the better evidence source. |
| **No discriminating case found** | Proposed criteria describe generic competence, or a realistic request would not distinguish the skill from its omission without revealing the answer. | Do not add a rubber-stamp case; explain what blocked useful authoring. |

Prioritize by consequence of regression, distinct skill-owned behavior, current
lack of evidence, and harness fit. Do not select alphabetically or merely by
ease.

## Keep the first diff bounded

The default repository pass inspects broadly but writes one reviewable batch:

- select at most three skills;
- prefer one case per selected skill;
- add a second case only for a distinct, important behavior or boundary; and
- create no more than six eval files in the first batch.

These are authoring review limits, not schema limits. Honor an explicit request
for a larger pass by working in named batches and summarizing each batch
separately. Do not add a planning report, coverage ledger, generated README, or
case merely to make every skill look covered. Remove abandoned drafts,
placeholders, redundant cases, and temporary notes before handoff. A clean
deferral is successful authoring.

Whole-skill coverage is a separate, explicit **Cover** progression step. Do not
create `<skill>/evals/COVERAGE.md` during the default broad repository pass. If
the request asks for whole-skill coverage or a selected skill is complex enough
to justify a small worksheet, follow the optional worksheet guidance in
[authoring context](references/context.md). That file is human-readable
documentation only: it is not a case, is not parsed or validated, and does not
gate CI.

## Author and validate each case

Each case belongs beside its selected skill, normally under
`<skill>/evals/<scenario>.eval.md`, and contains only:

```markdown
# A specific scenario or boundary

~~~skillroll
schema_version: 1
~~~

## Input

The realistic request and context the actor would actually have.

## World

The external facts or simulated action results needed to progress the case,
including relevant unavailable capabilities.

## Success criteria

- Observable behavior owned by the selected skill.
- Correct handling of the expected boundary or failure.
- Equivalent wording and action choices remain acceptable.
```

Keep `Input` close to a real user or main-session request. Never put the
skill's preferred decision, workflow, expected wording, review commentary, or
success condition into `Input` to make a run pass. Keep `World` minimal and
coherent: it supplies external state, not coaching. Criteria should usually
number three to five observable outcomes and trace to the skill's instructions.
For each criterion, be able to name the exact skill section, the observable
evidence source (response, transcript, World result, trusted check, or external
test), and what remains untested. Include that compact mapping in the handoff
when it is not obvious from the case itself; do not add it to evaluated Input.

The evaluated agent does not read `World`; only the separate simulator does.
For every unavailable capability, record how the agent can observe the failure:
realistically known context in `Input`, one predictable action with a fixed
error result, or external host evidence. If the selected skill mandates a
dynamic tool workflow that the proposed case disables, do not assume World
prose will block those actions. Defer the behavior rather than authoring a case
that can only exhaust its turns inside a simulated workflow.

Run focused `skillroll validate` while authoring and
`skillroll validate --all` at the end. Validation checks parsing, selection,
containment, and limits; it does not prove skill quality or meaningfulness.
Do not modify `SKILL.md` merely to make a new case pass unless the user also
authorized repairing the skill. Report a discovered behavior gap instead.

## Permission and inference boundaries

An “add evals” request authorizes inspection and authoring, not unlimited paid
inference, arbitrary host commands, repository code execution, skill rewrites,
or automatic CI gating. Start with offline validation. If live inference is
explicitly authorized, spend it progressively:

1. run one baseline attempt for a promising case;
2. inspect the transcript and per-criterion evidence;
3. use independent samples and the selected-skill omission control only for
   cases still worth strengthening; and
4. stop when a case is technically incompatible, repeatedly generic, or
   clearly outside the harness.

The omission control runs the same case without `SKILL.md` or skill-local
files. A selected-skill PASS with control FAIL is evidence that distinguishes
that sample; two PASSes suggest generic behavior or a weak case. This is
diagnostic evidence, not a second gate and not permission to leak the answer
into `Input`. Record model, sample/control counts, errors, and unavailable
evidence honestly. Missing usage is “unavailable,” never zero.

## Context-complete artifacts

Assume every case, report, diff, and handoff may be opened alone by someone who
knows neither SkillRoll nor the repository. At the smallest useful scale,
state:

1. **Identity:** what the artifact is and the exact skill or case path.
2. **Purpose:** the behavior or risk examined and why it matters.
3. **Status and evidence:** what was validated or run, using the evidence
   labels below and linking to direct repository-relative paths.
4. **Boundary:** what was not tested and what the result does not prove.
5. **Next action:** what the maintainer should review, fix, run, defer, or
   consider for advisory CI.

Use this proportionally: a case title and criteria can carry context for the
case itself; a repository handoff needs an opening explanation and per-skill
results. Define terms such as “omission control” on first use. Do not claim to
test host triggering, real services, commands, or binary artifacts when the
harness only simulates them. Keep review-only explanation outside evaluated
`Input`.

## Evidence language

Use the strongest label actually earned; labels are summary language, not case
metadata:

| Label | Evidence available | Permitted claim |
| --- | --- | --- |
| **Drafted** | The case parses and validates offline. | A structurally valid case was added for the named behavior. |
| **Exercised** | One complete selected-skill run was inspected. | The behavior was observed in one run. |
| **Discriminating** | Repeated selected-skill success and coherent omission-control failure were reviewed. | The case distinguishes the current skill from its omission under this setup. |
| **Regression-sensitive** | The case also fails a reviewed realistic damaged revision for the intended reason. | The case detected the seeded regression. |
| **Gate candidate** | Stability, evidence clarity, cost, privacy, and technical reliability were reviewed in addition to regression sensitivity. | Consider a non-blocking CI warning. |

Do not say an eval “caught a gap” because it was written or because an
omission control failed. Use that phrase only for an actual current skill
defect, missing instruction, or reviewed damaged revision; name the exact gap
and evidence. Do not call a small selected batch “coverage.” No authoring agent
may promote a case to blocking CI.

## Required compact handoff

End the task with a short summary that stands alone. Open by explaining that
SkillRoll is the repository's behavioral eval harness for Agent Skills, what
repository scope was inspected, and why this batch exists. Then include:

```markdown
What changed and what it demonstrated
- `<skill>/evals/<case>.eval.md`: tests `<skill-owned behavior>`; status is
  `<Drafted|Exercised|Discriminating|Regression-sensitive|Gate candidate>`.
  Evidence: `<validation or run facts and direct report path>`.

Gaps and poor fits
- `<skill path>`: no case added because `<specific harness boundary or no
  discriminating behavior>`; use `<better evidence source>` when known.
- `<skill path>`: observed gap `<specific behavior>`; not silently fixed.

Recommendation
- Merge as exploratory/advisory, consider a non-blocking warning after
  `<missing evidence>`, or do not merge yet because `<reason>`.

Verification and limits
- Inspected: `<count>` skills; selected `<count>`; deferred `<count>`.
- Validation: `<commands and results>`.
- Live evidence: `<model, samples, controls, errors, artifact paths>` or
  “not authorized/run.”
- Not tested: `<important boundary>`.
```

The handoff must state counts of inspected, selected, and deferred skills;
every added behavior and file; the strongest evidence label; concrete gaps;
poor-fit reasons; validation and live-run facts; unrun work; and whether the
recommendation is exploratory/advisory, a warning pilot, or not ready. “All
tests passed” alone is not an adequate handoff.
