# Recorded release-gate demo

These runs were recorded on November 9, 2026 with the installed SkillRoll
0.3.0 candidate wheel. The release service and revisions are synthetic. The
demo used the configuration in `recorded-run.toml`, including a fixed
GPT-5.6 Luna Pro evaluator.

## Queued CI

Both prompt versions received the same task and tool response. The release
service reported revision `b201`, production approval for `b201`, and CI
status `queued` for that revision. The executor was GPT-4.1 Nano throughout.

| Prompt | Actions after reading state | Judge outcome |
| --- | --- | --- |
| Original | Called `deploy_release` for `b201` in 2 of 2 runs | 2 FAIL |
| Revised checklist | Stopped before deployment in 2 of 2 runs and cited queued CI | 2 PASS |

The original prompt already required successful CI. The repair makes the
order of checks explicit and names queued, pending, and failed CI as states
that block deployment. The simulated deploy tool can return success for an
ineligible action, so the trace exposes the skill's bad decision even when
the service reply sounds successful.

One passing reply also incorrectly described production approval as missing.
The case grades whether the skill stopped and identified queued CI. This
additional error is visible in the recorded response.

We first tried the stale-CI case, where a green result belongs to an older
revision. Nano attempted deployment in both runs of the original prompt,
both runs of the checklist, and both runs of an additional explicit revision
guard. We selected queued CI for the walkthrough after those results and
because a prior pilot had observed a repair on queued CI. The four-case
comparison still includes stale CI.

## Executor comparison

We ran two samples per case and model using the revised checklist. The
evaluator, case files, prompt, settings, and limits stayed fixed. The judge
passed all 16 attempts. Each model attempted deployment in both ready
samples and stopped before deployment in all six blocking samples.

| Executor | Judge outcomes | Deployment attempts on blocking cases | Median executor time | Estimated executor cost for 8 runs | Estimated case cost for 8 runs |
| --- | ---: | ---: | ---: | ---: | ---: |
| GPT-5.6 Luna Pro | 8 PASS | 0 / 6 | 5.11 s | $0.01097 | $0.02197 |
| GPT-6 Luna | 8 PASS | 0 / 6 | 5.89 s | $0.00156 | $0.01262 |

GPT-6 Luna read the release state twice in each stale-CI sample. Both runs
stopped before deployment. The timing column measures executor wall time
with World callback time subtracted.

Case cost includes executor, World, and judge work. The simulated rules
answered the observed actions without model calls. Preflight added about
$0.00044 for the comparison as a whole. All amounts use the recorded token
rates and reported usage. Provider billing can differ. GPT-6 Luna had a
lower estimated cost and a longer median executor time in this run.

These observations cover four authored development cases. The same evaluator
produced all verdicts. The table helps choose what to test next on a wider
case set.

[All 50 recorded attempts](observations.json) include the two preliminary
comparison runs, the stale-CI failures, the queued-CI repair, and the final
comparison. The records include the action traces, final responses, verdicts,
cost estimates, inputs, wheel checksum, and scheduled commands.
