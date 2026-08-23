# Setup context

Install the isolated CLI with:

```shell
uv tool install skillroll
```

`skillroll init` chooses the skills directory and can add starter cases. In
an interactive terminal it offers OpenRouter's free compatible router, while
`--yes` and `--yes --openrouter-free` are explicit non-interactive choices
(`--yes` alone leaves inference unset). Init never reads a key or contacts an
endpoint.

`validate` is inference-free. `doctor` checks the configured compatible endpoint
after its named key is set in the environment. `eval --all` is the first
command that spends inference. The free router is appropriate only for checking
that this pipeline works; use a pinned named model for skill-quality evidence.
A generated GitHub workflow is opt-in and uses an explicit released Action
reference.

For a first-use answer, show the commands in this order: install, `init`,
`validate`, export the named key, `doctor`, then `eval --all`. Missing
`skillroll.toml` and a missing key are expected before `init`; do not describe
them as blockers for the inference-free setup steps.
