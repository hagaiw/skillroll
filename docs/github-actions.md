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
- Manual runs accept an exact reviewed revision and selected scope.
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
output. Use short retention or disable uploads for sensitive repositories.

See the [security model](security.md) and [results](results.md).
