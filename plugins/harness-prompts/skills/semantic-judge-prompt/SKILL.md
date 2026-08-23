---
name: semantic-judge-prompt
description: Use when SkillRoll must judge one completed skill evaluation from its authored criteria and observed evidence without executing either actor.
---

# SkillRoll semantic-judge contract

This internal dogfood skill describes the evidence-only model actor used by
`src/skillroll/judge.py` after one evaluated-skill attempt completes. The
judge sees the realistic Input, Success criteria, final output, and ordered
action transcript. It does not see the selected skill or authored World prose.

It must assess every authored criterion independently, credit only completed
final-output or transcript evidence, reject promised, inferred, reconstructed,
unsupported, or contradicted evidence, audit factual modifiers when a criterion
requires factual grounding without inventing new evidence requirements, respect
returned errors, and return the strict JSON
decision contract. It must not execute the skill, simulate the World, invent
repository state, or reject equivalent action terminology unless the criteria
explicitly require it.

**Instruction-only boundary:** apply this contract in the current response.
Do not call `world_action`, `semantic-judge-prompt`, `Skill`, or another action
to delegate or simulate the judgment. Those actions cannot decide the case and
their returned prose is not judge evidence. A bounded `Read` of this skill's
packaged references is allowed only when their exact text is needed.

Read [judge context](references/context.md) for this dogfood case's evidence
boundary and [the exact packaged judge prompt](references/system.md) for the
runtime contract. The evaluated `Input` remains a realistic request; it is not
an answer key for the judge.
