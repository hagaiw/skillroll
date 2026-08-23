---
name: skillroll-setup
description: Use when a repository owner needs help with authoritative SkillRoll setup commands.
---

# SkillRoll setup

**Instruction-only skill:** answer with setup guidance; do not call `Skill`,
`Read`, `Write`, or any other tool. Tool results must not replace the command
path below.

Guide the owner through installing the current SkillRoll package, then
`skillroll init`, `skillroll validate`, `skillroll doctor`, and
`skillroll eval --all` in that order. Explain what each command does and use
its diagnostics as the authority. Do not write a key into a file or pretend
setup tested a model before doctor succeeds.

## First-use path

When the owner has a skills folder but no `skillroll.toml` or API key, that is
the expected starting state. Give this short path directly; do not ask the
owner to create configuration by hand:

1. Install the CLI: `uv tool install skillroll`.
2. Create configuration without inference:
   `skillroll init --skills-path <skills-folder> --yes`.
3. Check the repository without inference:
   `skillroll validate --all`.
4. Add an OpenAI-compatible endpoint, export its named key, and run
   `skillroll doctor`.
5. Only after `doctor` passes, spend inference with `skillroll eval --all`.

`init` and `validate` do not need a configuration file or API key before they
run. This skill explains commands; it does not execute them or simulate setup
with a `Skill` action. Do not stop at a question such as “would you like help?”
when the owner asked for setup guidance.

Interactive `init` may offer OpenRouter's free compatible router as an
onboarding convenience. It never reads the key or contacts the endpoint. The
owner must explicitly create and export the configured key variable (which is
`OPENROUTER_API_KEY` for the free defaults) before `doctor`; `--yes` remains
inference-free, and scripts can use `--openrouter-free` explicitly. Explain
that the free route is only a setup/pipeline sanity test: its selected model
and availability can change, so a named model is required for skill-quality
or release evidence.

Read [setup context](references/context.md) for safe command examples.
