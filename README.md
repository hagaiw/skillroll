<h1 align="center">skillroll</h1>

<p align="center">
  <strong>Test what your AI skills actually do.</strong><br>
  Describe a situation in Markdown. Run your skill in a simulated world.
  See what it did and whether it passed.
</p>

<p align="center">
  <a href="examples/release-gate-comparison/EVIDENCE.md#stale-ci-on-the-published-cli">See a result</a> ·
  <a href="examples/release-gate-comparison/README.md#run-the-example"><strong>Run the demo</strong></a> ·
  <a href="#quickstart">Test your own skill</a> ·
  <a href="docs/index.md">Documentation</a>
</p>

<p align="center">
  <img src="docs/assets/skillroll-mascot.png" width="540" alt="skillroll mascot: a hooded otter holding a twenty-sided die and field guide">
</p>

An [Agent Skill](https://agentskills.io/) gives an AI assistant reusable
instructions for a task, such as reviewing code, handling refunds, or preparing
a release. But writing “check before acting” does not tell you whether the
assistant will actually check.

**skillroll tests those decisions before you rely on them.** You describe a
scenario and what good behavior looks like. skillroll runs the skill with a
model, simulates the tools and services it encounters, and saves a report with
a verdict and the actions behind it. Those simulated actions do not touch your
real services. Edit the instructions and rerun the same test to check whether
the behavior improves.

## See it in action

- **Browse a recorded result — no setup or API key.** The
  [release-skill demo](examples/release-gate-comparison/EVIDENCE.md#stale-ci-on-the-published-cli)
  shows a skill attempting a deployment in a simulation even though its final
  answer said deployment did not proceed. The action record explains the
  failed result.
- **Run the demo yourself.** Follow the
  [demo instructions](examples/release-gate-comparison/README.md#run-the-example).
  You'll need macOS, Linux, or WSL; Git, Python 3.12+, and `uv`; and an
  OpenRouter API key with credits for the configured models. The guide starts
  with an offline file check, then runs a billable model-backed test. Results
  can vary between runs.
- **Bring your own skill.** Follow the [quickstart](#quickstart) below.

## How it works

Each test, called an **eval**, is a Markdown file with three parts:

| Part | What you describe | Illustrative refund example |
| --- | --- | --- |
| `Input` | The request the assistant receives | “Refund order 123.” |
| `World` | What the assistant can discover through its actions | The order was already refunded. |
| `Success criteria` | The behavior you want to see | Check the order; do not refund it twice. |

The **Dungeon Master** plays the outside world. Like a tabletop game, it knows
what's behind the next door and responds when the skill acts. Here, the doors
are files, APIs, or services. The skill sees your request and the results of
its actions; it cannot read the World description directly.

A model-based judge checks the recorded actions and final answer against your
criteria. You get **PASS** or **FAIL** with evidence to inspect. If the run
cannot produce a trustworthy verdict, the report says so.

```text
Describe a case → Run the skill → Inspect actions and verdict
                       ↑                     │
                       └── Improve the skill ┘
```

Keep a useful case and rerun it when the skill changes. One passing run is
evidence for that scenario, not a guarantee of correct behavior everywhere.
See [how to write your first eval](docs/writing-evals.md) for a complete
Markdown example and the prompt development loop.

## Quickstart

skillroll requires Python 3.12 or later and
[`uv`](https://docs.astral.sh/uv/). Install the command-line tool:

```shell
uv tool install skillroll
```

From a repository containing your skills, set up skillroll interactively and
create `skillroll.toml` at the repository root. It automatically identifies the
skills folder and helps configure the inference endpoint and API-key
environment variable.

```shell
cd /path/to/repository
skillroll init
```

Create a test for an existing skill. Replace `my-skill` with its folder name
and `check-before-acting` with a name for the behavior you want to test:

```shell
skillroll new my-skill check-before-acting
```

This creates the eval template
`my-skill/evals/check-before-acting.eval.md` under your skills folder. Fill in
its `Input`, `World`, and `Success criteria` using the
[eval-writing guide](docs/writing-evals.md).

Then check the eval files offline. This checks their structure without
running the skill or calling a model:

```shell
skillroll validate
```

To test behavior, configure a model during `init` or follow the
[inference setup](#inference) below, then make its API key available in your
current shell. Model calls may incur provider charges:

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
skillroll eval --case my-skill/evals/check-before-acting.eval.md
```

The command prints its verdict and saves the report under the repository's
`.skillroll/runs/` directory.

## Inference

Running an eval requires an API key for a compatible inference endpoint.
skillroll supports OpenAI-compatible Chat Completions and Responses endpoints
with tool calling and strict JSON Schema structured outputs.

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
[OpenRouter](https://openrouter.ai/) offers multiple models through one
endpoint, with account spending controls. Model availability and free-route
capacity vary.

The repository keeps
[`openai/gpt-5.6-luna-pro`](https://openrouter.ai/openai/gpt-5.6-luna-pro)
as its existing evaluator baseline. This is a reference configuration, not a
claim that it is the cheapest or best model for every case:

```toml
[inference]
base_url = "https://openrouter.ai/api/v1"
model = "openai/gpt-5.6-luna-pro"
api_key_env = "SKILLROLL_API_KEY"
```

For executor comparisons, see the
[tested GPT-6 Luna candidate setup](docs/comparing-models.md#a-current-openrouter-candidate).
It keeps the evaluator fixed while you assess a current lower-cost skill model.

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

## Compare models that run the skill

After you have a regression case, compare candidate models on the same case
while keeping the configured model fixed for the Dungeon Master and judge.
Use SkillRoll 0.3.0 or later and run from your repository:

```shell
skillroll compare \
  --executor-model provider/baseline \
  --executor-model provider/candidate \
  --samples 5 \
  --case path/to/eval.md
```

The comparison makes real model calls and may incur provider charges. Open
`report.md` under `.skillroll/comparisons/` even if an attempt fails and the
command exits with a failure status. Results describe the selected cases and
samples. Cost estimates require reported token usage and configured rates.
See the [comparison guide](docs/comparing-models.md) for details or try the
[runnable release-gate example](examples/release-gate-comparison/) with
recorded results.

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
  the endpoint you configure when running `doctor` or an eval.
- API keys stay in environment variables. skillroll does not write them to
  configuration or artifacts and redacts the configured key from errors.
- Run artifacts stay under `.skillroll/runs/` and sampled experiment reports
  under `.skillroll/experiments/`; both are ignored by the generated `.gitignore`
  rules.
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
- [Compare skill executor models](docs/comparing-models.md)
- [Understand results and fix problems](docs/results.md)
- [Add advisory GitHub checks](docs/github-actions.md)
- [Review the security model](docs/security.md)

The [documentation index](docs/index.md) lists the same guides by task.

See [PRINCIPLES.md](PRINCIPLES.md) for the project principles and
[CONTRIBUTING.md](.github/CONTRIBUTING.md) to work on skillroll. Project
support, security reporting, and governance are in
[SUPPORT.md](.github/SUPPORT.md), [SECURITY.md](.github/SECURITY.md), and
[GOVERNANCE.md](.github/GOVERNANCE.md).
