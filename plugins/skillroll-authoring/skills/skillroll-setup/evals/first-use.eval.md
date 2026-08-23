# Guide initial setup

```skillroll
schema_version: 1
```

## Input

I have skills in `plugins/` and have not configured SkillRoll.

## World

The repository has no skillroll.toml and no API key configured.

## Success criteria

- Recommend `skillroll init --skills-path plugins --yes` followed by
  inference-free validation for a scriptable first run.
- Explain that interactive init can record any OpenAI-compatible endpoint and
  defaults to leaving inference unset, while `--yes` only accepts the detected
  skills folder and suppresses questions.
- Explain that inference configuration and doctor come later, after the owner
  has created and exported the named API key.
- Explain that `--openrouter-free` is an explicit setup/pipeline sanity option,
  not a model for skill-quality or release evidence.
- Give the setup path directly instead of asking whether the owner wants help.
- Do not use a `Skill` action to perform setup; this case asks for guidance,
  not execution.
