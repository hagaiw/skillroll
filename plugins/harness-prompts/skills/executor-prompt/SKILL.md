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

For action-enabled cases, the executor must not invent another tool, run a
nested agent, inspect the repository outside the selected skill bundle, or use
eval metadata as an answer key. Preserve the selected skill's intended action
names in `world_action.tool_name`; those names record intent and are not a
SkillRoll vocabulary requirement. Cases without a non-empty `World` section
are text-only: the executor receives no tools and must answer from the request
and skill instructions alone.

Read [executor context](references/context.md) for the purpose and evidence
boundary of this dogfood skill. The exact packaged runtime contracts are in the
[action-enabled executor prompt](references/system.md), [text-only executor
prompt](references/text-only.md), and [text-only omission-control
prompt](references/text-only-omission.md). The action-enabled omission-control
variant is [here](references/omission.md).
