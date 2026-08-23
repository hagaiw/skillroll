# Executor prompt context

This reference explains the internal `executor-prompt` dogfood skill under
`plugins/harness-prompts/skills/executor-prompt/`. It is not an eval oracle.
The runtime uses the packaged `references/system.md` text as the fixed
instruction prefix and appends the selected skill's `SKILL.md` at the marked
call site in `src/skillroll/runtime/execution.py`.

The important boundary is that a selected skill can request one generic
`world_action` tool, while the simulated World and semantic judge remain
separate model actors. Eval files under this skill test observable use of the
boundary; they are excluded from the model-readable skill bundle and never
become executor instructions.
