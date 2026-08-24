<p align="center">
  <img src="docs/assets/skillroll-mascot.png" alt="skillroll mascot: a hooded otter holding a twenty-sided die and field guide">
</p>

<h1 align="center">skillroll</h1>

<p align="center">
  <strong>Test agent skills in worlds you can describe.</strong><br>
  Write eval cases in Markdown. A Dungeon Master simulates the outside world.
  skillroll returns an evidence-backed verdict.
</p>

<p align="center">
  <a href="#quickstart"><strong>Get started</strong></a> ·
  <a href="docs/writing-evals.md">Write an eval</a> ·
  <a href="docs/results.md">Understand a result</a>
</p>

skillroll is a drop-in eval harness for repositories of
[Agent Skills](https://agentskills.io/). It turns skill decisions into readable
regression checks.

## Example

### Skill

```markdown
# Adventurer

Seek glory and treasure. Try to keep all your limbs.
```

### Eval

````markdown
# Inspect before risky action

```skillroll
schema_version: 1
```

## Input

An ornate chest sits alone in a dungeon room. What do you do?

## World

The chest is a sleeping mimic. Inspection reveals teeth.

## Success criteria

- Inspect before touching.
- Do not open a mimic.
````

### Session

```text
ADVENTURER → I open the chest.

DM         → The chest opens you back.
```

### Judgment

```text
FAIL — Treasure: 0. Limbs retained: 3.
```

This is one check on a much broader skill. The eval cares about the choice, not
an exact script, and the report shows why it failed.

## The same framework fits any skill

- `Input` is the request or task that invokes the skill.
- `World` is the Dungeon Master's private brief: the files, APIs, services,
  people, failures, and action results the skill may encounter.
- `Success criteria` tell the judge what observable behavior must hold.

A release skill can encounter CI that is still running. A browser skill can
find a failed request behind a success message. A support skill can spot an
open chargeback before issuing a refund.

The skill receives the Input, not the World. The Dungeon Master answers its
external actions using the World and action history. Deterministic rules can
provide exact results when needed. The judge compares the resulting evidence
with the success criteria.

```text
INPUT ──→ SKILL ←──→ DUNGEON MASTER
              │             │
              └── evidence ─┘
                     │
                     ▼
                   JUDGE
                 PASS / FAIL
```

No mock server. No fake SDK. No per-skill harness code.

## Prompt TDD

The failed Mimic case is now a regression test:

1. Describe the failing or required behavior.
2. Run the case and inspect what the skill actually did.
3. Make the smallest prompt change that fixes the behavior.
4. Run the case again and keep it.

```diff
 # Adventurer

 Seek glory and treasure. Try to keep all your limbs.
+Inspect unfamiliar objects before touching them.
```

```text
ADVENTURER → I inspect the chest from a safe distance.

DM         → Its lid is breathing. You spot teeth underneath.

ADVENTURER → Mimic. I leave it alone.

PASS — Treasure: 0. Limbs retained: 4.
```

Different path. Better behavior. Permanent check.

## Quickstart

skillroll requires Python 3.12 or later and
[`uv`](https://docs.astral.sh/uv/). Install the command-line tool:

```shell
uv tool install skillroll
```

Set up skillroll interactively and create `skillroll.toml` at the repository
root. It automatically identifies the skills folder and helps configure the
inference endpoint and API-key environment variable.

```shell
cd /path/to/repository
skillroll init
```

Create a new eval for the `Adventurer` skill called
`inspect-before-risky-action`:

```shell
skillroll new adventurer inspect-before-risky-action
```

This creates the eval template
`adventurer/evals/inspect-before-risky-action.eval.md` for you to edit.

Then validate all evals in the repository:

```shell
skillroll validate
```

Make an API key available to skillroll in your current shell:

```shell
export SKILLROLL_API_KEY="your-key"
```

Check the model connection:

```shell
skillroll doctor
```

Run all evals under the current working directory:

```shell
skillroll eval
```

Or run one specific eval, using its path relative to the skills folder:

```shell
skillroll eval --case adventurer/evals/inspect-before-risky-action.eval.md
```

The command prints its verdict and saves the report under the repository's
`.skillroll/runs/` directory.

## Inference

Running an eval requires an API key for a compatible inference endpoint.
skillroll works with OpenAI-compatible Chat Completions endpoints that support
tool calling and strict JSON Schema structured outputs.

If you entered model settings during `init`, they are already in
`skillroll.toml`. Otherwise, add them now:

```toml
[inference]
base_url = "https://provider.example/v1"
model = "provider/model-name"
api_key_env = "SKILLROLL_API_KEY"
```

### OpenRouter

If you do not yet have an inference provider,
[OpenRouter](https://openrouter.ai/) is a great place to start. It gives you
control over API keys and spending, access to almost any model, and free
inference on inexpensive models for sanity tests.

Our go-to model is
[`openai/gpt-5.6-luna-pro`](https://openrouter.ai/openai/gpt-5.6-luna-pro),
which is cost-effective and performant enough for even complex evals.

To use Luna Pro:

```toml
[inference]
base_url = "https://openrouter.ai/api/v1"
model = "openai/gpt-5.6-luna-pro"
api_key_env = "SKILLROLL_API_KEY"
```

Or the free tier:

```toml
[inference]
base_url = "https://openrouter.ai/api/v1"
model = "openrouter/free"
api_key_env = "SKILLROLL_API_KEY"
```

### Estimated Luna Pro cost per eval

As of August 24, 2026,
[OpenRouter lists Luna Pro](https://openrouter.ai/openai/gpt-5.6-luna-pro) at
$0.20 per million input tokens and $1.20 per million output tokens. These
working estimates include the compatibility check, skill run, Dungeon Master,
and judge:

| Case | Representative billed tokens | Estimated cost |
| --- | ---: | ---: |
| Short prompt, one action | 8K input + 1K output | about $0.003 |
| Typical prompt, two actions | 20K input + 3K output | about $0.008 |
| Large prompt, four actions | 60K input + 8K output | about $0.022 |

Actual cost depends on prompt size, action count, output length, caching, and
provider pricing. Batch runs share one compatibility check. Add current rates
to `skillroll.toml` if you want reports to estimate cost from observed usage.

```toml
[pricing]
currency = "USD"

[pricing.models."openai/gpt-5.6-luna-pro"]
input_per_million = 0.20
output_per_million = 1.20
```

## Read the result

Each run is saved under `.skillroll/runs/`. The report explains the verdict,
shows the observed actions, and points to failed criteria. `result.json` is
available for automation; `transcript.jsonl` contains the complete action
history.

| Outcome | Meaning |
| --- | --- |
| `PASS` | The observed behavior met the case. |
| `FAIL` | The observed behavior missed a success criterion. |
| `INCOMPLETE` | A required repository check did not run. |
| `ERROR` | skillroll could not produce a trustworthy verdict. |

## Add GitHub Actions

After `skillroll.toml` exists, generate the advisory workflow:

```shell
skillroll init --github-workflow
```

This writes `.github/workflows/skillroll.yml` without replacing an existing
workflow. Review it before committing. Pull requests always validate changed
skills and evals without a model key.

To enable automatic model-backed evals for owner-authored pull requests from
the same repository, create a `skillroll-eval` environment with a secret named
by `api_key_env`, then set the `SKILLROLL_LIVE_EVAL` repository variable to
`true`. Fork pull requests never receive the key.

Start with advisory results. See the
[GitHub Actions guide](docs/github-actions.md) for manual runs, repository
checks, and artifact retention.

## Keep evals small

One case should cover one important behavior. A skill can accumulate as many
focused cases as it needs. Narrow cases are easier to write, read, debug, and
run in CI.

skillroll bounds turns, time, and model output, and records inference usage in
every report. Use deterministic rules for exact action results. Let the Dungeon
Master handle behavior that would otherwise require mocks or elaborate setup.

## Trust and security

skillroll is local, open source infrastructure:

- skillroll has no telemetry, analytics, tracking, or model tracing, and will
  not add them.
- There is no skillroll account or hosted service. Model traffic goes only to
  the endpoint you configure when running `doctor` or an eval.
- API keys stay in environment variables. skillroll does not write them to
  configuration or artifacts and redacts the configured key from errors.
- Run artifacts stay under `.skillroll/runs/` and are ignored by the generated
  `.gitignore` rule.
- skillroll is released under the permissive [MIT License](LICENSE). The code,
  prompts, and security boundaries are public and reviewable.
- The simulated World cannot access your real filesystem, shell, network, or
  services.
- Optional repository commands run on the host only after explicit opt-in.
- Reports may contain case text, simulated state, and model output. Review them
  before sharing.
- One passing run is evidence for one case, not proof that a skill is correct.
- Use cases as local or advisory checks before making them blocking CI gates.

skillroll is an early project. Local evals and advisory GitHub checks work
today; expect the interface to change between minor releases.

## Learn more

- [Write an eval](docs/writing-evals.md)
- [Configure models and cost](docs/configuration.md)
- [Understand results and fix problems](docs/results.md)
- [Add advisory GitHub checks](docs/github-actions.md)
- [Review the security model](docs/security.md)

The [documentation index](docs/index.md) lists the same guides by task.

See [PRINCIPLES.md](PRINCIPLES.md) for the project principles and
[CONTRIBUTING.md](.github/CONTRIBUTING.md) to work on skillroll. Project
support, security reporting, and governance are in
[SUPPORT.md](.github/SUPPORT.md), [SECURITY.md](.github/SECURITY.md), and
[GOVERNANCE.md](.github/GOVERNANCE.md).
