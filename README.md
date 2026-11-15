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
  <a href="docs/authoring.md">Author skills and evals</a> ·
  <a href="docs/writing-evals.md">Write an eval</a> ·
  <a href="docs/results.md">Understand a result</a>
</p>

Skills such as [Agent Skills](https://agentskills.io/) give an AI assistant
reusable instructions for a job. skillroll tests the decisions the assistant
makes with those instructions and turns them into readable regression checks.

## Example

This dungeon scenario illustrates how to write a case and read the result.

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

## How it works

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

Use the folder name of an existing skill in place of `adventurer` if needed.
This creates an eval template under that skill's `evals/` directory. Fill in
`Input`, `World`, and `Success criteria`, then check the files offline:

```shell
skillroll validate
```

Set the API key in the environment variable named by `api_key_env`.
The default name is `SKILLROLL_API_KEY`:

```shell
export SKILLROLL_API_KEY="your-key"
```

Check the model connection. This and the eval call the configured model
provider and may incur charges:

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
skillroll works with OpenAI-compatible Chat Completions and Responses
endpoints that support tool calling and strict JSON Schema structured outputs.

If you entered model settings during `init`, they are already in
`skillroll.toml`. Otherwise, add them now:

```toml
[inference]
base_url = "https://provider.example/v1"
model = "provider/model-name"
api_key_env = "SKILLROLL_API_KEY"
```

### OpenRouter

The [bundled demo](examples/release-gate-comparison/README.md#run-the-example)
uses OpenRouter with a named model and a checked-in configuration. The guide
starts with offline file validation. Running the skill requires an OpenRouter
API key with credits for the configured models.

See the [configuration guide](docs/configuration.md) for provider setup, model
options, and cost estimates.

### Estimated cost per eval

As of November 15, 2026, OpenRouter lists
[GPT-5.6 Luna Pro](https://openrouter.ai/openai/gpt-5.6-luna-pro) at $0.20
per million input tokens and $1.20 per million output tokens on standard
routing. These examples use that model for the skill, Dungeon Master, and judge.
The token totals are illustrative and include a compatibility check for one
standalone run. A batch can share that check.

| Example | Total input tokens | Total output tokens | Estimated cost |
| --- | ---: | ---: | ---: |
| Short prompt, one action | 8K | 1K | $0.0028 |
| Typical prompt, two actions | 20K | 3K | $0.0076 |
| Large prompt, four actions | 60K | 8K | $0.0216 |

For a measured point of reference, the [recorded release demo comparison](examples/release-gate-comparison/EVIDENCE.md#executor-comparison)
averaged about **$0.0016 per case** with GPT-6 Luna running the skill and
GPT-5.6 Luna Pro judging it, plus about $0.00044 in shared compatibility checks
for the whole comparison. That estimate uses the recorded token usage across
eight runs of four cases. Actual charges depend on the model, token usage,
caching, and provider rates.

To estimate costs in your own reports, add the rates for your models to
`skillroll.toml`. See the [cost configuration guide](docs/configuration.md#optional-cost-estimates).

```toml
[pricing]
currency = "USD"

[pricing.models."openai/gpt-5.6-luna-pro"]
input_per_million = 0.20
output_per_million = 1.20
cache_read_per_million = 0.02
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

The generated pull-request job uses one sample and no no-skill control. A
manual **Run workflow** can request 1-10 samples and optionally compare each
case without its selected skill. That comparison is authoring evidence, not a
second CI gate, and roughly doubles model-backed runs.

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
  the endpoint you configure when running `doctor`, `eval`, or `compare`.
- API keys stay in environment variables. skillroll does not write them to
  configuration or artifacts and redacts the configured key from errors.
- Run, experiment, and comparison artifacts stay under `.skillroll/`. The
  generated `.gitignore` rules cover those directories.
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

- [Author and audit good skills and evals](docs/authoring.md)
- [Write an eval](docs/writing-evals.md)
- [Configure models and cost](docs/configuration.md)
- [Compare models on the same cases](docs/comparing-models.md)
- [Understand results and fix problems](docs/results.md)
- [Add advisory GitHub checks](docs/github-actions.md)
- [Review the security model](docs/security.md)

The [documentation index](docs/index.md) lists the same guides by task.

See [PRINCIPLES.md](PRINCIPLES.md) for the project principles and
[CONTRIBUTING.md](.github/CONTRIBUTING.md) to work on skillroll. Project
support, security reporting, and governance are in
[SUPPORT.md](.github/SUPPORT.md), [SECURITY.md](.github/SECURITY.md), and
[GOVERNANCE.md](.github/GOVERNANCE.md).
