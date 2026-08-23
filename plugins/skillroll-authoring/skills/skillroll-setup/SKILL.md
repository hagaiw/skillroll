---
name: skillroll-setup
description: Use when a repository owner needs the shortest safe path from an existing skills folder to a first SkillRoll eval.
---

# SkillRoll setup

SkillRoll drops into an existing skills repository. `init` creates its small
configuration and can add starter Markdown cases; `validate` checks them without
inference; `doctor` checks the model connection; and `eval` runs the cases.

## First-use path

When the owner has a skills folder but no `skillroll.toml` or API key, give this
path directly:

1. Install the CLI: `uv tool install skillroll`.
2. Create configuration without inference:
   `skillroll init --skills-path <skills-folder> --yes`.
3. Check the repository without inference: `skillroll validate --all`.
4. Configure an OpenAI-compatible endpoint, export its named key, and run
   `skillroll doctor`.
5. After `doctor` passes, run `skillroll eval --all`.

`init` and `validate` do not need a configuration file or API key before they
run. Never put a key in `skillroll.toml` or claim that setup tested a model
before `doctor` succeeds.

Interactive `init` asks whether to record any OpenAI-compatible endpoint and
defaults to no. `--yes` only accepts the detected skills folder and suppresses
questions; it does not configure inference. Scripts can explicitly use
`--openrouter-free` for a setup sanity check. Use a named model for stable
skill-quality or release evidence.

**Instruction-only skill:** answer with setup guidance; do not call `Skill`,
`Read`, `Write`, or any other tool. This skill does not execute them or simulate setup.
It never performs setup with a `Skill` action. Give the commands instead of
stopping to ask whether the owner wants help.

Read [setup context](references/context.md) for safe command examples.
