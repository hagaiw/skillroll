# GitHub Actions

Generate a workflow in a skills repository with:

```shell
skillroll init --github-workflow
```

`init` does not replace an existing workflow. Review
`.github/workflows/skillroll.yml` before committing it.

## What the workflow does

- Pull requests validate changed skills and cases without a model key.
- Trusted same-repository owner changes can run live cases and upload evidence.
- Fork pull requests never receive the inference key.
- Manual dispatch accepts an exact reviewed revision and selected scope.
- Repository checks run only through a separate, secretless manual option.
- Published release events validate the tagged repository.

The generated YAML is authoritative. Check its Action reference, permissions,
artifact retention, and selected commands before enabling it.

## Start advisory

Use local runs while authoring. Install the workflow without making its live
job a required status check, then review failures until each case has shown
stable and useful signal. Repeated noise should improve or demote a case.

The generated workflow evaluates the proposed revision's cases, so a pull
request can change behavior and its test together. Teams that create blocking
checks are responsible for protecting and qualifying their cases.

## Configure the key

Create a `skillroll-eval` environment with an environment secret matching
`api_key_env` in `skillroll.toml`. Add a required reviewer if live runs should
wait for approval. To enable automatic live evaluation for same-repository
owner pull requests, also create the repository variable
`SKILLROLL_LIVE_EVAL` with the value `true`. The generated workflow exposes the
secret only to live inference steps. Validation and repository-check jobs do
not receive it.

Repository checks are unsandboxed and may use the runner's network or other
available credentials. Review the exact revision before enabling them. Uploaded
evidence can contain case text, model output, and bounded command output; use
short retention or disable uploads for sensitive repositories.

See the [security model](security.md) and [results](results.md).
