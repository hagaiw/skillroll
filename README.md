# SkillRoll

SkillRoll is a small behavioral eval framework for
[Agent Skills](https://agentskills.io/). Write a Markdown case beside a skill,
run it in a controlled simulated world, and review the verdict and evidence.

Use it to turn an important prompt behavior into a readable regression case
before changing the prompt.

> If you can explain what a skill should do, you can eval it.

## Status

SkillRoll is an early project. Local evaluation and advisory GitHub checks work
today; expect the interface to evolve between minor releases.

A passing run means one observed attempt met one case. It is useful evidence,
not proof that a skill is correct or ready for blocking CI.

## Quickstart

SkillRoll requires Python 3.12 or later and
[`uv`](https://docs.astral.sh/uv/).

```shell
uv tool install skillroll
```

Initialize a repository that already contains `SKILL.md` files:

```shell
skillroll init \
  --repo /path/to/my-skills \
  --skills-path skills \
  --starter-evals my-skill \
  --yes

skillroll validate --repo /path/to/my-skills --all
```

`skills_path` is relative to the target repository. `--starter-evals` and
`--case` are relative to `skills_path`. Validation is offline: it does not need
an API key or call a model.

Open the generated case under `my-skill/evals/`, replace the placeholders, and
delete any starter case you do not need. A case has three parts:

- `Input`: the realistic request and context given to the skill;
- `World`: simulated external state and action results; and
- `Success criteria`: observable outcomes that allow equivalent good answers.

Configure an OpenAI-compatible Chat Completions endpoint in
`skillroll.toml`:

```toml
schema_version = 1
skills_path = "skills"

[inference]
base_url = "https://provider.example/v1"
model = "provider/model-name"
api_key_env = "SKILLROLL_API_KEY"
```

The endpoint must support tool calling and strict JSON Schema structured
outputs. Export the configured key, check compatibility, and run a case:

```shell
export SKILLROLL_API_KEY="your-key"
skillroll doctor --repo /path/to/my-skills
skillroll eval \
  --repo /path/to/my-skills \
  --case my-skill/evals/first-use.eval.md
```

`doctor` checks the endpoint. `eval` spends inference and writes a private run
under `.skillroll/runs/`. Start with `report.md`; use `result.json` for
automation and `transcript.jsonl` to inspect the skill's actions.

| Outcome | Meaning |
| --- | --- |
| `PASS` | The observed evidence met the case. |
| `FAIL` | One or more expectations were not met. |
| `INCOMPLETE` | A required repository check was not run. |
| `ERROR` | The run could not produce a trustworthy verdict. |

## Know the boundaries

- Simulated World actions cannot access your real filesystem, shell, network,
  services, or other skills.
- Optional repository checks are ordinary host commands, not a sandbox. They
  run only after explicit opt-in.
- Evidence can contain case text, simulated state, action results, and model
  output. Review it before sharing.
- Free or changing model routes are useful for setup checks, not comparable
  skill-quality evidence. Pin a named model when results need to be compared.
- Start behavioral cases as manual or advisory checks. Promote them only after
  their failures are stable, specific, and useful.

## Learn more

- [Write an eval](docs/writing-evals.md)
- [Configure models and cost](docs/configuration.md)
- [Understand results and fix problems](docs/results.md)
- [Add advisory GitHub checks](docs/github-actions.md)
- [Review the security model](docs/security.md)

The [documentation index](docs/index.md) lists the same guides by task.

See [PHILOSOPHY.md](PHILOSOPHY.md) for the project principles and
[CONTRIBUTING.md](CONTRIBUTING.md) to work on SkillRoll. Project support,
security reporting, and governance are in [SUPPORT.md](SUPPORT.md),
[SECURITY.md](SECURITY.md), and [GOVERNANCE.md](GOVERNANCE.md).
