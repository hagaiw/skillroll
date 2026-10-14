# GitHub Actions

SkillRoll can add an advisory eval workflow to a skills repository:

```shell
skillroll init --github-workflow
```

`init` writes `.github/workflows/skillroll.yml` and does not replace an
existing workflow. Review the generated file before committing it.

## What runs

- Pull requests validate changed skills and cases without a model key.
- Pull requests opened by the repository owner from the same repository can run
  model-backed cases and upload evidence.
- Fork pull requests never receive the inference key.
- Manual runs accept an exact reviewed revision and selected scope. They can
  also request 1-10 independent samples and an optional no-skill comparison.
- Repository checks run only through a separate, secretless manual option.
- Published releases validate the tagged repository.

Review the generated Action reference, permissions, artifact retention, and
commands before enabling the workflow.

## Start with advisory results

Use local runs while writing or fixing a skill. Add the workflow without making
its model-backed job a required check. Review failures until each case gives
stable, useful feedback. Improve or demote a noisy case.

The workflow evaluates the proposed revision's cases, so a pull request can
change a skill and its case together. Protect and qualify cases before using
them as blocking checks.

The generated pull-request job always uses one sample and no no-skill control.
For authoring diagnostics, use **Actions → SkillRoll → Run workflow**, enter
the exact reviewed revision and scope, then choose a sample count from 1 to 10
and whether to run the selected cases without their skill. A no-skill
comparison roughly doubles model-backed runs and is diagnostic evidence, not a
second gate.

This creates the same prompt development loop in CI: preserve a failure as a
case, fix the skill, and catch the behavior if it returns.

## Configure the key

Create a `skillroll-eval` environment with an environment secret matching
`api_key_env` in `skillroll.toml`. Add a required reviewer if model-backed
runs should wait for approval.

To enable automatic evaluation for pull requests opened by the repository
owner from the same repository, create the repository variable
`SKILLROLL_LIVE_EVAL` with the value `true`. The workflow exposes the secret
only to model-backed evaluation steps. Validation and repository-check jobs do
not receive it.

Repository checks are unsandboxed and may use the runner's network or other
available credentials. Review the exact revision before enabling them.
Uploaded evidence can contain case text, model output, and bounded command
output. Sampled runs also upload their parent report under
`.skillroll/experiments/`. Use short retention or disable uploads for sensitive
repositories.

See the [security model](security.md) and [results](results.md).

## Changed-case selection

The Action's `changed` scope computes one explainable plan. Adding or modifying
one eval selects that case; changing a skill prompt, reference, or script selects
that skill's cases. Renames consider both paths; deleted evals select the
remaining cases for their skill. An unknown path, missing configuration, or
unmappable removal selects the full suite. An unreadable diff also falls back to
the full suite. Full offline structure validation still precedes inference.

Repositories can explicitly pass the `impact-policy` Action input to a reviewed
repository-relative TOML file:

```toml
schema_version = 1
offline = ["tests/**", "docs/**", ".github/workflows/release.yml"]
full = ["shared-prompts/**"]

[[dependencies]]
changed = "skills/shared-runner/**"
affected = ["skills/release-flow/**"]
```

Globs match repository-relative paths. Skill/eval paths take precedence over
offline exemptions. Configuration, Action metadata, policy edits, and declared
full-suite paths always select the full suite. Eval-only changes do not expand
broad skill dependencies; an explicit source ending in `.eval.md` can declare
a dependency on an eval. Reverse dependencies expand transitively, including
cycles. Combine all targets under a single `changed`
source; a dependency target without discoverable cases widens to the full suite.
Exemptions are reviewed declarations, not automatic source dependency analysis.
Unknown paths remain conservative. Malformed policies fail instead of silently
skipping evaluation.

Use `mode: plan` with `scope: changed` and the same base/head SHAs and policy to
inspect selected cases and reasons without using a model key. The plan is
included in JSON output and GitHub summaries. Use `scope: all` without a policy
to explicitly request the full suite.

## Concurrent cases

`skillroll eval --all --concurrency 4` evaluates up to four independent cases at
a time. The CLI and Action default to one; the `concurrency` Action input accepts
1-16. Generated automatic workflows default to four and allow a repository
variable `SKILLROLL_EVAL_CONCURRENCY` to lower or raise the cap. Manual workflows
expose a concurrency input. Use an Action revision containing these features;
the published `v0.1.2` Action does not support them.

Each case retains ordered world actions, separate executor/world state, and its
own evidence directory. Reports stay in stable case order even when cases finish
out of order. Preflight is shared once for the chosen profile. Samples and
skill-omission controls remain sequential batches. Cancellation drains workers
before closing shared transport resources.

Repository commands require concurrency 1 because they can mutate shared files.
Parallelism reduces elapsed time, not the number of evaluations or their intended
inference budget. Start with a small cap and review duration, provider errors,
and cost; reduce the cap if throttled. Technical failures and behavioral failures
remain visible, and model requests are not silently retried.

## SkillRoll's own repository

This repository uses `.github/skillroll-impact.toml` for both its secretless plan
and its live run, replacing the separate workflow-only filter. Mixed PRs union
the affected cases without letting unrelated tests, release automation, setup,
or presentation helpers expand the plan. Shared harness prompt references select
every case. The policy explicitly records the `flow-runner` reverse dependencies
and tests them against plugin metadata so new dependent plugins cannot silently
be omitted. Source files not explicitly exempted select every case; this includes
runtime, judge, parser, inference, and world code.

Offline jobs run candidate code with read-only permissions and no inference key.
Automatic live runs use that same exact candidate's local Action only for
owner-authored, same-repository PRs with `SKILLROLL_LIVE_EVAL=true`, inside the
`skillroll-eval` environment. Candidate Python and Action code receive the eval
key: configure environment reviewers and review that revision before approving.

This repository defaults automatic and manual live runs to concurrency 1 because
observed parallel requests exceeded the provider account's in-flight reservation
budget. Set `SKILLROLL_EVAL_CONCURRENCY` or the manual concurrency input to raise
the cap after checking the account's available budget; generated downstream
workflows retain their default of four.

Fork PRs never enter that credentialed path. This fixes the gap where changing
harness source still executed the old published harness.

Manual runs validate the entered revision format using the released Action,
then evaluate the explicitly reviewed checkout's candidate code through the
same environment. Downstream generated workflows continue to pin their chosen
published Action; they do not execute their skills repository as harness code.
