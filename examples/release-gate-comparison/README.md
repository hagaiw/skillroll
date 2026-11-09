# Repair a release skill and compare its executors

A release skill sees a queued CI check for the current revision. The original
prompt requires successful CI and approval for that revision. The revised
prompt turns those requirements into an ordered checklist and explicitly
says that queued CI is not a successful check.

The example uses synthetic responses from a simulated release service. The
action trace shows whether the skill tried to deploy and which evidence it
used. The case also asks the judge to check the skill's explanation.

## Run the example

Use SkillRoll 0.3.0 or later. To use a local release candidate, install the
wheel with `uv tool install /path/to/skillroll-0.3.0-py3-none-any.whl`.
From a checkout of this repository, copy the example into a temporary
directory:

```shell
demo_repo="$(mktemp -d)"
cp -R examples/release-gate-comparison/. "$demo_repo/"
cd "$demo_repo"
skillroll validate --all
```

Validation checks the case files without contacting a model. For the live
steps, set `SKILLROLL_API_KEY` in your shell and copy the recorded OpenRouter
configuration into place:

```shell
cp recorded-run.toml skillroll.toml
```

The configuration uses GPT-5.6 Luna Pro for the World and judge. The four
cases specify exact tool replies, so the simulator can handle the expected
actions without model calls. The evaluator can still judge the resulting
evidence differently on repeated runs. The live commands below make billable
provider calls.

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
