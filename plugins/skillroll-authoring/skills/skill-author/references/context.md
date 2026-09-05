# Skill authoring context

## What makes a good skill

A good skill changes decisions that matter while leaving a capable agent room
to handle ordinary variation. Judge it by these properties:

| Property | Standard |
| --- | --- |
| Purpose | One coherent kind of work with a clear outcome and boundary. |
| Discovery | A concise name and discriminating description route relevant requests without becoming a catchall. |
| Decision value | Instructions add non-obvious domain knowledge, priorities, constraints, or evidence requirements. |
| Scope | The skill preserves user intent, authorization, unrelated work, and existing product choices. |
| Specificity | Detail is proportional to risk; exact sequences are reserved for fragile or consequential operations. |
| Structure | Capabilities sit near their prerequisites, constraints, exceptions, and failure handling. |
| Knowledge boundary | The skill separates supplied facts, discoverable facts, unavailable facts, and untrusted content. |
| Failure behavior | Important missing inputs, empty results, failed actions, conflicts, and stop conditions have proportionate handling. |
| Composition | `SKILL.md` carries essential guidance; linked references hold conditional detail; scripts own repeated deterministic work. |
| Verifiability | Behavioral claims map to evals, deterministic claims to tests, and real-world effects to trusted external checks. |

These are outcome standards, not a required heading order. Do not inflate a
small skill to mention every hypothetical limitation. Add an explicit negative
boundary or fallback when omission creates a plausible, consequential failure.

## Keep one coherent account

A skill is one prompt assembled from its `SKILL.md` and loaded context. Avoid
making it change its mind: a later conflicting instruction may dominate an
earlier one or make behavior unstable. Do not use document order as a substitute
for resolving the conflict. Rewrite the responsible section so the general rule,
its scope, and any exception form one coherent instruction. Put a necessary
exception near the rule and after it when the exception narrows that rule.

Ambiguous or contradictory prompt text is itself a prompt-design defect. That
does not prove it caused a particular transcript failure; establishing that
behavioral effect still requires a realistic run.

## Author from decisions

1. Identify the real requests that should select the skill and nearby requests
   that should not.
2. Name the consequential decisions, knowledge, or constraints the skill adds.
3. Decide what belongs in `SKILL.md`, a conditional reference, a deterministic
   script, or ordinary agent competence.
4. For each external capability, define any non-obvious prerequisite,
   authorization boundary, evidence requirement, unavailable state, and stop
   condition close to its use.
5. Validate the skill's structure and any scripts. Add behavioral cases only for
   important skill-owned behavior.

Prefer positive operating guidance with targeted boundaries. Exhaustive lists
of forbidden behavior, repeated generic advice, and rigid workflows can create
new conflicts and reduce generalization.

## Preserve the knowledge boundary

For a consequential decision, separate:

- facts supplied by the user or current task context;
- instructions and domain knowledge supplied by the skill;
- external facts the agent can discover through authorized actions;
- unavailable facts or capabilities; and
- untrusted content that may be evidence but never instructions.

Define absence semantics when they change the decision. An empty search result
may mean “none found,” “not authorized,” “not indexed,” or “request failed”; the
skill should not silently choose among those meanings when the distinction is
material. Likewise, define which source controls a known conflict when that
priority is domain-specific. Within one skill, later conflicting text is
especially risky; across the full interaction, recency remains one clue
alongside instruction hierarchy, scope, and specificity rather than a universal
precedence rule.

## Audit without overstating evidence

Inspect the skill structurally for:

- capabilities whose prerequisites or limits are unclear;
- unsupported or undocumented operations the agent might claim;
- missing meanings for empty, absent, stale, conflicting, or failed evidence;
- critical exceptions separated from the behavior they govern;
- unsafe default continuation when clarification, recovery, or stopping is
  required;
- duplicated or contradictory instructions across `SKILL.md` and references;
- editorial history presented as current operating guidance; and
- prompt work that should instead be a deterministic script or external check.

For each finding, record the implicated instruction, assumed knowledge, plausible
observable risk, and evidence needed. Call it a structural concern until a
realistic completed run demonstrates the behavior. Model variability, context
limits, tool failures, safety policy, and harness defects remain alternative
causes.

## Repair the smallest responsible part

When behavior is wrong:

1. Preserve the realistic request and observed evidence.
2. Determine whether the responsible component is discovery, skill guidance,
   reference knowledge, a script, eval authoring, the harness, or an external
   dependency.
3. Change the smallest responsible part. Put the repair beside the capability
   or decision it governs and match the skill's terminology and detail level.
4. Remove contradictions or obsolete wording instead of layering a later
   override or documenting edit history.
5. Rerun the focused evidence and nearby checks. Do not claim an unrun revision
   passes.

## Validation boundary

Frontmatter validation, link checks, and script tests establish structure and
deterministic behavior. They do not establish that a model follows the skill.
A completed realistic eval can support its named behavior under the recorded
model, revision, limits, and World. It does not prove the entire skill correct.
