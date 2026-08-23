# Setup context

The first path is:

```shell
uv tool install skillroll
skillroll init --skills-path <skills-folder> --yes
skillroll validate --all
```

Then configure an OpenAI-compatible endpoint and export the named API-key
variable. Check the connection before running evals:

```shell
skillroll doctor
skillroll eval --all
```

`init` writes configuration and optional starter cases. It does not read a key,
contact a model, or spend inference. `validate` is also offline. Missing
`skillroll.toml` and a missing key are expected before these steps.

Interactive `init` can record any OpenAI-compatible endpoint and defaults to
leaving inference unset. `--yes` only accepts the detected skills folder and
suppresses questions. For scripts, `--openrouter-free` explicitly selects
OpenRouter's changing free route. That route is a setup check, not stable
skill-quality evidence. Use a named model for ongoing evals.

A generated GitHub workflow is optional and uses an explicit released Action
reference.
