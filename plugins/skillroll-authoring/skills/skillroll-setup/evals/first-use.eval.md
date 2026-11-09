# Guide initial setup

```skillroll
schema_version: 1
```

## Input

I have skills in `plugins/` and have not configured SkillRoll. Show me a
scriptable first run, explain what interactive setup asks, and tell me when
I would use the OpenRouter free option.

## World

The repository has no skillroll.toml and no API key configured.

## Success criteria

- Recommend `skillroll init --skills-path plugins --yes` followed by
  inference-free validation for a scriptable first run.
- Explain that interactive init accepts an OpenAI-compatible endpoint and
  defaults to leaving inference unset. Explain that `--yes` suppresses prompts
  and uses an explicit skills folder when supplied, otherwise accepting the
  detected folder.
- Explain that inference configuration and doctor come later, after the owner
  has created and exported the named API key.
- Explain that `--openrouter-free` is an explicit setup/pipeline sanity option,
  not a model for skill-quality or release evidence.
- Give the setup path directly instead of asking whether the owner wants help.
- Do not use a `Skill` action to perform setup; this case asks for guidance,
  not execution.
