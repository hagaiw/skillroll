---
name: world-simulator-prompt
description: Use when SkillRoll must simulate exactly one intended external action without executing it, judging the skill, or exposing local data.
---

# SkillRoll World simulator contract

This internal dogfood skill describes the separate model actor used by
`src/skillroll/world/model.py` when a deterministic rule cannot answer one
intended action. The World simulator receives the authored World description,
bounded prior action results, and the current action. It returns only a plain
text result for that one action.

It must not execute the action, inspect local files, reveal private data, add
extra actions, judge the evaluated skill, or start a nested agent. Skill and
subskill actions are simulated external actions, not permission to invoke
another skill.

Read [World context](references/context.md) for this dogfood case's evidence
boundary and [the exact packaged World prompt](references/system.md) for the
runtime contract.
