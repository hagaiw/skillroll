# Compare executor models

The `compare` command and executor model options in this guide are in the
upcoming release and are not in the released `v0.2.0` CLI. To try them before
release, use a SkillRoll source checkout containing this change: run
`uv sync --locked`, then run the command with `uv run skillroll` and `--repo
PATH` for the repository you want to evaluate. After release, use the
installed `skillroll` command from that repository.

`skillroll compare` runs the same selected cases with several candidate models
as the skill executor. The configured `model`, or the model chosen by
`--model-profile`, remains fixed for the Dungeon Master and judge. The
comparison can help you choose a skill model for a particular skill and case
set; it does not prove that two models are equivalent.

This command makes real model calls and may incur provider charges. The
`validate` command checks case structure offline; it does not run a comparison.

## Run a comparison

Use one or more cases that represent the behavior you care about. This example
runs five samples on one eval:

```shell
uv run skillroll compare \
  --repo /path/to/your-repository \
  --executor-model provider/baseline \
  --executor-model provider/candidate \
  --samples 5 \
  --seed 0 \
  --case path/to/eval.md
```

The command accepts 2–8 unique `--executor-model` values and 1–10 samples. Pass
`--case PATH`, `--skill PATH`, or `--all` to select the evals; `--repo PATH`
selects the repository. Use `--model-profile NAME` to choose the evaluator
profile, or `--run-commands` when you explicitly want trusted repository checks
to run. The comparison ignores a configured `executor_model`: its repeated
`--executor-model` arguments define the candidates.

Candidates run serially. The first candidate is the baseline for paired counts
in the report. SkillRoll preflights each distinct model used in the comparison
before it starts the cases. Once a comparison starts, model assignments stay
fixed; SkillRoll does not switch models partway through an attempt.

`--seed` controls run order only; it does not seed model responses. The World
is generative, so repeated attempts can differ even with the same case, seed,
model names, and configuration.

## A current OpenRouter candidate

For a low-cost executor candidate, test `openai/gpt-6-luna` against your existing
model. The following shared settings were exercised through OpenRouter on
November 8, 2026 with GPT-6 Luna and both base and Pro GPT-5.6 Luna executors:

```toml
[inference]
base_url = "https://openrouter.ai/api/v1"
model = "openai/gpt-5.6-luna-pro"
api_key_env = "SKILLROLL_API_KEY"
wire = "chat_completions"
supports_temperature = false

[inference.extra_body]
reasoning_effort = "none"
```

From the source checkout, compare the candidates on your own cases:

```shell
uv run skillroll compare \
  --repo /path/to/your-repository \
  --executor-model openai/gpt-5.6-luna-pro \
  --executor-model openai/gpt-5.6-luna \
  --executor-model openai/gpt-6-luna \
  --samples 5 --all
```

The evaluator stays at the existing baseline. This recipe verifies a supported
request setup; it does not establish the best executor or validate the
baseline's judging accuracy. Base and Pro routes can use different amounts of
reasoning even when their listed token rates match. Check current
[model guidance](https://developers.openai.com/api/docs/models/gpt-6-luna) and
[gateway pricing](https://openrouter.ai/openai/gpt-6-luna), then use returned
usage and your own cases to assess cost and behavior. Gateway settings and
routes can change.

## Read the evidence

Comparison artifacts are written under
`.skillroll/comparisons/comparison-<id>/`. It contains three files:

- `manifest.json` is written before inference. It records the selected model
  order, SkillRoll version, configuration and pricing, and fingerprints of the
  selected skills, evals, installed harness source, and effective prompts, plus
  key dependency versions. It records a hash of
  `[inference.extra_body]`, not the parameter values.
- `comparison.json` is the machine-readable report and checkpoint. It records
  compatibility-preflight evidence and each planned attempt. Pending attempts
  remain `NOT_RUN`; completed attempts point to their normal run evidence.
- `report.md` is the human-readable comparison report.

Each attempt keeps its own normal run evidence under `.skillroll/runs/`.

Each candidate is paired with the baseline on the selected case and sample. The
baseline counts are descriptive: they summarize these observed runs only. They
are not confidence estimates, an equivalence test, or proof that a lower-cost
candidate matches the baseline's quality. Repeated samples reveal some
run-to-run variation on the selected cases; they do not increase coverage of
different tasks.

SkillRoll does not retry samples or remove errors from the report. If inputs
change while the comparison is running, it stops with an `ERROR` and retains
the unfinished schedule.
There is no resume operation; running the command again creates a new
comparison ID and a new set of evidence.

## Compare quality and cost carefully

Before comparing models, make evals from realistic, self-contained `Input`
scenarios and useful success criteria. Develop the cases first, then freeze a
held-out set before using it to choose a model. If you change a case after
seeing comparison results, treat the changed case as development data and
reserve other cases for a fresh check.

Use failures on development cases to improve the skill prompt, then compare
again on the held-out cases. SkillRoll evaluates these changes; it does not
automatically optimize prompts or fine-tune model weights.

Review failed attempts and transcripts, especially severe or irreversible
mistakes. Check whether a result reflects the skill, the World, or the success
criteria. A judge can apply a criterion too strictly or miss a subtle failure;
keep hard safety requirements explicit and use deterministic repository checks
for exact constraints when possible.

Use the per-role usage and cost evidence to weigh quality against expense.
Compatibility preflight usage is reported separately from case work. Cost is
estimated only when the provider reports token usage and your
`[pricing.models]` table has matching rates; either missing value makes cost
unavailable, not zero. Keep any rates you use current yourself. The report's
wall time after subtracting World callbacks is a harness proxy, not a measure
of production latency.

The artifacts record model names and configuration; they do not fingerprint
the inference weights or provider routing behind a model name. A later run may
reach different weights or provider behavior under the same name. Read the
[configuration guide](configuration.md) for endpoint and pricing settings and
the [results guide](results.md) for normal run evidence.
