<p align="center">
  <img src="docs/assets/skillroll-mascot.png" alt="SkillRoll mascot: a hooded otter holding a twenty-sided die and field guide">
</p>

<h1 align="center">SkillRoll</h1>

<p align="center">
  <strong>Regression tests for AI agent skills.</strong><br>
  Turn a real prompt failure into a readable case, run it in a bounded world,
  and inspect the evidence before the behavior ships again.
</p>

<p align="center">
  <a href="#quickstart"><strong>Get started</strong></a> ·
  <a href="docs/writing-evals.md">Write an eval</a> ·
  <a href="docs/results.md">Understand a result</a>
</p>

![SkillRoll demo: create a wait-for-CI eval, edit it, run it, and read the judge summary](docs/assets/skillroll-demo.gif)

SkillRoll is a behavioral eval framework for
[Agent Skills](https://agentskills.io/). Keep a Markdown case beside a skill,
run the skill in a controlled simulated world, and get a verdict with
reviewable evidence.

> If you can explain what a skill should do, you can eval it.

## The loop

1. **Capture** one important behavior as `Input`, `World`, and observable
   `Success criteria`.
2. **Run** the skill without exposing your filesystem, network, or services to
   the simulated World.
3. **Inspect** the report, fix the smallest responsible prompt, and keep the
   case as a regression test.

![Dark SkillRoll evidence summary showing required E2E still running and the merge correctly withheld](docs/assets/evidence-report.png)

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

From a repository that already contains `SKILL.md` files:

```shell
cd /path/to/my-skills
skillroll init --yes
skillroll new my-skill/first-use
```

SkillRoll detects the common folder containing your skills. Use
`--skills-path PATH` only when you need to override it. `new` creates one
no-overwrite template at `my-skill/evals/first-use.eval.md`.

Open the generated case under `my-skill/evals/` and replace the placeholders.
A case has three parts:

- `Input`: the realistic request and context given to the skill;
- `World`: simulated external state and action results; and
- `Success criteria`: observable outcomes that allow equivalent good answers.

Check the case structure before spending inference:

```shell
skillroll validate --case my-skill/evals/first-use.eval.md
```

Validation is offline: it does not need an API key or call a model.

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
skillroll doctor
skillroll eval --case my-skill/evals/first-use.eval.md
```

`doctor` checks the endpoint. `eval` spends inference and writes a private run
under `.skillroll/runs/`; the command prints the exact `report.md` path. Use
`result.json` for automation and `transcript.jsonl` to inspect the skill's
actions.

## What SkillRoll is for

SkillRoll answers a narrow, practical question: **did this observed skill run
preserve the behavior this case describes?** It is useful while authoring or
changing a skill and as an advisory regression check in pull requests.

It is not a leaderboard, a universal skill score, or proof that a skill is
correct. For model research or claims about aggregate skill lift, use a
benchmark designed for repeated controlled comparison.

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
