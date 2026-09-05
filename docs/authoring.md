# Authoring skills and evals

SkillRoll treats skill design and eval design as related but separate work. A
skill supplies reusable operating guidance. An eval creates evidence about one
observable behavior without prescribing the prompt's wording or structure.

The canonical authoring standards live with the authoring skills:

- [Write and audit skills](../plugins/skillroll-authoring/skills/skill-author/references/context.md)
  explains scope, discovery, knowledge and capability boundaries, progressive
  disclosure, repair, and structural auditing.
- [Write and audit evals](../plugins/skillroll-authoring/skills/eval-author/references/context.md)
  explains realistic Input, private World state, observable criteria, knowledge
  boundaries, failure diagnosis, and evidence labels.

Use [Writing evals](writing-evals.md) for the CLI-oriented walkthrough. The
[project principles](../PRINCIPLES.md) state the shorter rules that changes to
SkillRoll itself must preserve.

## Evidence boundary

A prompt review can find ambiguity, missing prerequisites, undefined absence
semantics, or a constraint far from the capability it governs. Those findings
justify a candidate repair or eval; they do not by themselves prove model
behavior.

Use the smallest appropriate evidence source:

| Claim | Evidence |
| --- | --- |
| A skill or eval has valid structure | Offline validation and review |
| A model follows a skill in a particular scenario | A completed model-backed eval |
| A script or exact invariant works | A deterministic test |
| A real command, service, or artifact works | A trusted external check |

Record what actually ran and keep setup errors, authoring defects, behavioral
failures, and external failures separate.
