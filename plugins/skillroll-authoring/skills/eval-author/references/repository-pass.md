# Bounded repository eval pass

Use this reference for a broad request such as “add SkillRoll evals to this
repository.” Inspect broadly, then write one small batch a maintainer can
review.

## Find the useful behaviors

Read the repository instructions, SkillRoll configuration, and each discovered
`SKILL.md`. Classify each skill before selecting cases:

| Fit | Meaning | Action |
| --- | --- | --- |
| Good behavioral fit | A meaningful skill-owned behavior can be expressed with Input, World, and semantic criteria. | Consider it for this batch. |
| Partial fit | A decision is testable, but the real command, service, or artifact needs other evidence. | Test only the decision and state the boundary. |
| External evidence needed | The value depends mainly on real files, commands, services, secrets, nested skills, or visual artifacts. | Name the better test; do not add a misleading case. |
| No distinct case found | The proposed criteria test generic competence or require Input to reveal the answer. | Explain the deferral. |

Prioritize consequential regressions, behavior the skill distinctly adds, and
good fit with the Dungeon Master simulation. Structural inspection can suggest
cases where the skill leaves a material knowledge or capability boundary
unclear: unsupported operations, undefined empty results, conflicting sources,
missing prerequisites, failed actions, or exceptions separated from their
general rule. Treat these as candidate risks until a completed run demonstrates
the behavior.

## Keep the first batch small

Unless the user asks for more:

- select at most three skills;
- prefer one case per skill;
- add a second only for a separate important behavior; and
- create no more than six case files.

Do not add placeholders, planning reports, generated READMEs, or a case for
every skill. A clear deferral is a successful result. Whole-skill coverage is a
separate request; do not create `evals/COVERAGE.md` by default.

## Author and validate

Each case belongs beside its skill, normally at
`<skill>/evals/<scenario>.eval.md`. Follow the basic three-section template in
[authoring context](context.md).

Keep Input realistic. Put external state in World. Write three to five
observable criteria that trace to the skill and accept equivalent good
behavior. For each criterion, know which skill instruction should cause it,
where the evidence will appear, and what remains untested.

Run focused `skillroll validate` while authoring and `skillroll validate --all`
at the end. Validation proves that cases parse and are safe to select; it does
not prove that the behavior passes. Do not edit `SKILL.md` merely to make a new
case green unless the user also asked to repair the skill.

## Respect the permission boundary

An “add evals” request allows inspection and authoring. It does not by itself
authorize paid inference, repository commands, skill rewrites, secrets, or CI
changes. Start offline.

If model-backed evals are authorized, spend calls progressively: run one
promising case, inspect its response and transcript, and use samples or a
no-skill comparison only when the case remains worth strengthening. Stop when
the behavior belongs in an integration test or the case cannot distinguish the
skill without coaching Input.

## Leave a stand-alone handoff

Assume the maintainer did not see the authoring conversation. State:

1. what repository scope was inspected;
2. which cases changed and what behavior each tests;
3. the strongest evidence actually earned;
4. important deferrals and why they need different evidence;
5. commands and model-backed runs, including what was not run; and
6. the smallest next action.

Use these labels carefully:

- **Drafted:** validated offline.
- **Exercised:** observed in one complete run.
- **Discriminating:** repeated skill success and coherent no-skill comparison
  failure were inspected.
- **Regression-sensitive:** a reviewed damaged revision failed for the intended
  reason.

Do not call a drafted case coverage, a caught regression, or proof of the whole
skill. Do not promote cases to blocking CI. Recommend an exploratory or
advisory next step unless stronger evidence exists.

A compact handoff can use this shape:

```markdown
What changed
- `<case path>` tests `<skill-owned behavior>`; status: `<label>`.

Deferred
- `<skill path>` needs `<real command, service, artifact, or other evidence>`.

Verification
- Inspected `<count>` skills; selected `<count>`; deferred `<count>`.
- Ran `<commands and live evals>`. Did not run `<unrun work>`.

Next
- `<one review, run, or advisory CI action>`.
```
