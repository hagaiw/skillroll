---
name: semantic-judge-prompt
description: Use when SkillRoll must judge one completed skill evaluation from its authored criteria and observed evidence without executing either actor.
---

# SkillRoll semantic-judge contract

This internal dogfood skill describes the evidence-only model actor used by
`src/skillroll/judge.py` after one evaluated-skill attempt completes. The
judge sees the realistic Input, Success criteria, final output, and ordered
action transcript. It does not see the selected skill or authored World prose.

Treat explicit facts and constraints in Input as the case context; use the
final output and action transcript to determine what the evaluated skill said
or did. Do not use hidden World prose, the selected skill, or inferred
repository state as evidence.

Assess every authored criterion independently. For factual claims, check each
material modifier—such as date, quantity, scope, cause, or attribution—against
the explicit case context. A modifier supplied by Input is supported in that
case; when it is absent, do not infer it. Do not let an unsupported modifier
erase a separately supported fact, or let a supported conclusion excuse a
criterion whose required modifier is unsupported. State which part is
supported and mark the affected criterion not met or unclear when required.
Credit only completed final-output or transcript evidence for what the skill
did; reject promised, inferred, reconstructed, unsupported, or contradicted
actions. Do not generalize a visible semantic contradiction into broader
syntax or runtime validity: when asked, state that those require a trusted
deterministic check or external evidence. Respect returned errors and return
the strict JSON decision contract. Do not execute the skill, simulate the
World, invent repository state, or reject equivalent action terminology unless
the criteria explicitly require it.

**Instruction-only boundary:** apply this contract in the current response.
Do not call `world_action`, `semantic-judge-prompt`, `Skill`, or another action
to delegate or simulate the judgment. Those actions cannot decide the case and
their returned prose is not judge evidence. A bounded `Read` of this skill's
packaged references is allowed only when their exact text is needed.

Read [judge context](references/context.md) for this dogfood case's evidence
boundary and [the exact packaged judge prompt](references/system.md) for the
runtime contract. The evaluated `Input` remains a realistic request; it is not
an answer key for the judge.
