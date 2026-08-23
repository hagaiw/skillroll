# World simulator prompt context

This reference explains the internal `world-simulator-prompt` dogfood skill
under `plugins/harness-prompts/skills/world-simulator-prompt/`. The simulator
is not the evaluated skill and does not decide whether a case passes. It only
turns one unmatched intended action into a bounded external result while
honoring the authored World and visible prior results.

Reads inside the selected skill bundle and exact authored rules are handled by
SkillRoll before this actor is called. The packaged system resource is used
only for the remaining model-backed World action; eval files and Success
criteria never enter that system prompt.
