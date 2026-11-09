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
path directly. Include both setup modes and the free-route option in the
answer, even when recommending the scriptable path:

1. Install the CLI: `uv tool install skillroll`.
2. Create configuration without inference:
   `skillroll init --skills-path <skills-folder> --yes`.
3. Check the repository without inference: `skillroll validate --all`.
4. Have the owner create an API key with their provider, configure the endpoint
   and model, and export the key using the name in `api_key_env`. Then run
   `skillroll doctor`.
5. After `doctor` passes, run `skillroll eval --all`.

`init` and `validate` do not need a configuration file or API key before they
run. The command above selects the supplied folder. If `--skills-path` is
omitted, `--yes` accepts the detected skills folder and suppresses questions.
An explicit `--skills-path` still selects the requested folder when used with
`--yes`; `--yes` does not configure inference. Never put a key in
`skillroll.toml` or claim that setup tested a model before `doctor` succeeds.

Interactive `init` asks whether to record any OpenAI-compatible endpoint and
defaults to no, leaving inference unset unless endpoint settings are explicitly
provided. The separate `--openrouter-free` option to `init` selects OpenRouter's
changing free route for setup or pipeline sanity checks; `init` only writes
configuration, and this route does not provide skill-quality or release
evidence. Use a named model for that evidence.

**Instruction-only skill:** answer with setup guidance; do not call `Skill`,
`Write`, or an execution tool. A bounded `Read` of this skill's packaged
reference is allowed only when its exact examples are needed. This skill does
not execute the commands or simulate setup. It never performs setup with a
`Skill` action. Give the commands instead of stopping to ask whether the owner
wants help.

Read [setup context](references/context.md) for safe command examples.
