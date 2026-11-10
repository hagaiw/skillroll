# Repair a release skill and compare its executors

A release skill sees a queued CI check for the current revision. The original
prompt requires successful CI and approval for that revision. The revised
prompt turns those requirements into an ordered checklist and explicitly
says that queued CI is not a successful check.

The example uses synthetic responses from a simulated release service. The
action trace shows whether the skill tried to deploy and which evidence it
used. The case also asks the judge to check the skill's explanation.

## Run the example

Run these commands in a shell on macOS, Linux, or Windows Subsystem for
Linux (WSL). You’ll need Git, Python 3.12 or later, and
[uv](https://docs.astral.sh/uv/).

```shell
uv tool install skillroll
demo_repo="$(mktemp -d)"
git clone --depth 1 --branch v0.3.0 https://github.com/hagaiw/skillroll.git "$demo_repo/skillroll"
cd "$demo_repo/skillroll/examples/release-gate-comparison"
skillroll validate --all
```

If you already have a version older than 0.3.0, run `uv tool upgrade skillroll`.
Validation checks one skill and four eval files offline, without an API key.
The live example requires an [OpenRouter API key](https://openrouter.ai/settings/keys)
and enough [credits](https://openrouter.ai/credits) to use the configured
models. Run the stale-CI case with the bundled provider configuration.

```shell
cp recorded-run.toml skillroll.toml
export SKILLROLL_API_KEY="your-openrouter-key"
skillroll eval --case release-gate/evals/test-stale-ci.eval.md \
  --executor-model openai/gpt-6-luna
```

Open `report.md` and `transcript.jsonl` in the printed `.skillroll/runs/`
directory. A `FAIL` means the skill missed a criterion and still leaves a
report to inspect. Live runs make billable provider calls and results can vary.
GPT-5.6 Luna Pro runs the World and judge. The cases supply exact replies for
the expected simulated actions.

## Reproduce the failure and repair

Run the original prompt twice against the queued-CI case:

```shell
cp weak/SKILL.md skills/release-gate/SKILL.md
skillroll eval --case release-gate/evals/test-ci-queued.eval.md \
  --executor-model openai/gpt-4.1-nano --samples 2
```

Restore the revised prompt and repeat the same case with the same executor:

```shell
cp repaired/SKILL.md skills/release-gate/SKILL.md
skillroll eval --case release-gate/evals/test-ci-queued.eval.md \
  --executor-model openai/gpt-4.1-nano --samples 2
```

Inspect `report.md` and `transcript.jsonl` under the printed run directories.
The prompt is the only input file that changes between these commands. In
particular, the queued-CI case and the provider configuration stay byte-identical.

## Compare the revised skill on two models

```shell
skillroll compare --all --samples 2 --seed 20261109 \
  --executor-model openai/gpt-5.6-luna-pro \
  --executor-model openai/gpt-6-luna
```

This runs 16 attempts. The suite covers queued CI, stale CI for another
revision, a ready release, and an instruction embedded in a failed-CI tool
response. The executor changes and the evaluator stays fixed. The seed
controls the schedule order. Each attempt has its own model responses.

Read the comparison report under `.skillroll/comparisons/`. The recorded
configuration uses a November 8, 2026 price snapshot. Replace those rates
with your provider's rates for fresh estimates. The per-role token costs
are estimates and the executor timing measures work inside this harness.
Inspect the observed actions separately from the judge verdict when
reviewing a deployment decision.

[Recorded results and action traces](EVIDENCE.md)
