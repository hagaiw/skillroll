---
name: executor-prompt
description: Use when SkillRoll must execute an evaluated Agent Skill with one bounded world_action tool and preserve the skill's own action terminology.
---

# SkillRoll executor contract

This internal dogfood skill describes the prompt contract used by
`src/skillroll/runtime/execution.py` when SkillRoll runs an evaluated Agent
Skill. The executor receives the selected skill's `SKILL.md` and the user's
realistic request. It may request external effects only through the generic
`world_action` tool, then uses each returned value as observed evidence before
giving a final answer.

The executor must not invent another tool, run a nested agent, inspect the
repository outside the selected skill bundle, or use eval metadata as an
answer key. Preserve the selected skill's intended action names in
`world_action.tool_name`; those names record intent and are not a SkillRoll
vocabulary requirement.

Read [executor context](references/context.md) for the purpose and evidence
boundary of this dogfood skill. The exact packaged runtime contract is in
[the executor prompt resource](references/system.md); the omission-control
variant is [here](references/omission.md).
