# SkillRoll examples

These three small repositories are checked-in examples of different Agent
Skill boundaries. They use the current `skillroll.toml` and Markdown eval
format and contain no inference endpoint or API key.

Start with the [release-action-boundary](release-action-boundary/) example. It
checks required CI before merging and keeps an independent approval requirement
beside the release capability. Its two cases cover a running PR check and an
unresolved release approval. The root-level
`lead-weak.SKILL.md` and `lead-repaired.SKILL.md` files are comparison
fixtures, not discovered skills; only the bundle under `skills/` is validated.
No weak or repaired live outcome is included or implied; any authorized
comparison must preserve the frozen case and report what was actually observed.

The [support-text-judgment](support-text-judgment/) example turns supplied
support evidence into a concise response or handoff without inventing a
refund state. The [prompt-reference-script-composition](prompt-reference-script-composition/)
example keeps audience policy in a reference, repeated heading formatting in a
standard-library-only script, and content judgment in the prompt.

## Offline first-use path

The release-boundary example can be obtained from the public repository and
copied before changing directory:

```shell
git clone --depth 1 https://github.com/hagaiw/skillroll /tmp/skillroll-source
cp -R /tmp/skillroll-source/examples/release-action-boundary /tmp/skillroll-release-boundary
cd /tmp/skillroll-release-boundary
uv tool install skillroll
skillroll validate --all
```

`validate` is inference-free: it checks configuration, discovery, case
structure, and declared limits. A passing validation is structural evidence,
not a model result. The copied examples deliberately omit `[inference]`, so
they do not need a key.

To opt into credentialed checks, add the endpoint settings manually to
`skillroll.toml`:

```toml
[inference]
base_url = "https://provider.example/v1"
model = "provider/model-name"
api_key_env = "SKILLROLL_API_KEY"
```

Then set the named environment variable in the current shell, run
`skillroll doctor`, and only after it passes run `skillroll eval --all`.
`doctor` and `eval` are networked and credentialed; their outcomes depend on
the provider, model, case revision, and authorized run. Nothing in this
example bundle claims that a live run has occurred or that a real release,
refund, or customer action was performed.
