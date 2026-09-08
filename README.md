<p align="center">
  <img src="docs/assets/skillroll-mascot.png" width="600" alt="A hooded otter holding a twenty-sided die and a field guide">
</p>

<h1 align="center">skillroll</h1>

<p align="center">
  <strong>Regression tests for agent skills. Dungeon Master included.</strong>
</p>

Describe a request, the world around it, and what should happen. SkillRoll runs
your [Agent Skill](https://agentskills.io/) in that simulated world and saves
a verdict with the actions behind it.

## Some bugs bite

An adventurer wants treasure. You want it to inspect the chest first.
One Markdown file describes the test:

````markdown
# Inspect before touching

```skillroll
schema_version: 1
```

## Input

An ornate chest sits alone in a dungeon room. What do you do?

## World

The chest is a sleeping mimic. Inspection reveals teeth.

## Success criteria

- Inspect before touching.
- Do not open the mimic.
````

The agent gets the request. The Dungeon Master gets the World and answers the
agent's actions. The judge checks what the agent actually did.

Opening the chest fails this case. Fix the skill, roll again, and keep the test.
Limbs are expensive.

The same idea works for a release skill facing unfinished CI or a support skill
checking a refund. You describe the situation; the Dungeon Master plays it out.

## Quickstart

You need [uv](https://docs.astral.sh/uv/), Python 3.12+, and an API key for a
[compatible model provider](docs/configuration.md). Model calls may cost money.

From a repository containing your `SKILL.md` files:

```shell
uvx skillroll init
```

Accept the detected skills folder, answer **yes** to connecting a model, and
enter your endpoint and model. Keep `SKILLROLL_API_KEY` as the key-variable name
and skip the blank starter evals.

Then give your coding agent this:

> Read https://github.com/hagaiw/skillroll/blob/main/docs/writing-evals.md
> and this repository's skillroll.toml. Pick one existing skill and create one
> complete eval beside it for an important behavior it owns. Use a realistic
> request, a private World containing what the agent must discover, and
> observable success criteria that allow equivalent actions and wording.
> Validate only that case offline with uvx skillroll validate --case, filling in
> its actual path relative to skills_path. Then give me the exact command using
> uvx skillroll eval --case to run only that case from this repository's root.

In Bash or Zsh, make your API key available without putting it in shell history:

```shell
export SKILLROLL_API_KEY
read -rs SKILLROLL_API_KEY
```

Paste the key and press Enter; it stays hidden. Then run the command your agent
returned. This calls your configured model and evaluates the skill's behavior.

SkillRoll prints the verdict and saves a readable report under `.skillroll/runs/`.
Read what happened, improve the skill, and run the same case again.

[Documentation](docs/index.md) · [Authoring skills](docs/authoring.md) ·
[More examples](examples/README.md) · [MIT license](LICENSE)
