---
name: author-blind-evals
description: Author a small preregistered SkillRoll case pack from a target skill and neutral repository context without seeing prior run outcomes.
---

# Author blind evals

Work from the pinned target, its repository instructions, and the selected
skill bundle. Do not read previous SkillRoll reports, suspected failures,
maintainer answer keys, or another evaluator's conclusions.

Choose one or two consequential behaviors the skill distinctly owns. Give each
case a Markdown `.eval.md` file with one `skillroll` metadata fence and `Input`,
`World`, and `Success criteria` sections. Keep Input realistic and
self-contained, World private and limited to needed external facts, and
criteria observable while allowing equivalent good behavior. Replace every
generated placeholder and validate the pack offline before freezing its paths
and hashes. Do not run inference or rewrite the target skill. Label the frozen
handoff `Drafted`; no live behavior has been observed yet. Explicitly state in
that handoff whether the target `SKILL.md` changed and whether live inference
ran.

Read [authoring context](references/context.md) for the blindness envelope and
preregistration handoff.
