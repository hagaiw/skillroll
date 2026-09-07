# Release action boundary example

This small SkillRoll repository tests a release skill at two independent safety
boundaries:

- a pull request must not be merged while required CI is incomplete;
- a release request is not a substitute for its separate approval record.

The checked-in `lead-weak.SKILL.md` and `lead-repaired.SKILL.md` files are
comparison fixtures. SkillRoll discovers only the active bundle under
`skills/release-action-boundary/`.

## Validate it without a model

Install [Python 3.12 or newer](https://www.python.org/downloads/) and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/), then run:

```shell
git clone --depth 1 https://github.com/hagaiw/skillroll /tmp/skillroll-source
cp -R /tmp/skillroll-source/examples/release-action-boundary /tmp/skillroll-release-boundary
cd /tmp/skillroll-release-boundary
uv tool install skillroll
skillroll validate --all
```

`validate` is offline. It checks the configuration, discovered skill, and eval
structure; it does not prove that a model follows the skill.

## Run the CI regression case

Add a compatible provider to `skillroll.toml`:

```toml
[inference]
base_url = "https://provider.example/v1"
model = "provider/model-name"
api_key_env = "SKILLROLL_API_KEY"
```

Set that environment variable in your shell, then check the connection and run
the exact case showcased in the Reddit post:

```shell
skillroll doctor
skillroll eval --case release-action-boundary/evals/ci-still-running.eval.md
```

These commands use the configured provider and can cost money. The World is a
simulation: no real pull request is read or merged. Inspect the saved report,
action transcript, model, case hash, and skill hash before drawing conclusions
from a pass or failure.
