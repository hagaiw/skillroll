# Configuration

Use a named model for comparable evals. Free or changing routes are useful for
checking endpoint wiring, but their model and capacity can change.

## One model

```toml
[inference]
base_url = "https://provider.example/v1"
model = "provider/model-name"
api_key_env = "SKILLROLL_API_KEY"
```

The endpoint must provide an OpenAI-compatible Chat Completions API with tool
calling and strict JSON Schema structured outputs. Run
`skillroll doctor --repo PATH` before the first eval. SkillRoll does not
provide provider account support.

## Model profiles

A profile is an ordered preflight fallback for one purpose:

```toml
[inference]
base_url = "https://provider.example/v1"
api_key_env = "SKILLROLL_API_KEY"
default_profile = "authoring"

[inference.profiles.authoring]
purpose = "Normal authoring runs."
models = ["provider/primary", "provider/fallback"]
```

SkillRoll selects the first compatible candidate during preflight, then uses
that model for execution, World simulation, and judgment. It never switches
models mid-case. Use `--model-profile NAME` when no default is configured.

## Usage and estimated cost

Add optional rates that you maintain yourself:

```toml
[pricing]
currency = "USD"

[pricing.models."provider/primary"]
input_per_million = 0.40
output_per_million = 1.60
```

`result.json` reports stage usage when the provider supplies it and estimates
cost only when matching rates exist. Missing usage or pricing is unavailable,
not zero. SkillRoll does not fetch prices; check the provider's current rates
before budgeting.

Choose a model with representative cases. Compare completion rate, technical
errors, behavioral stability, latency, token use, and cost rather than relying
on the model name alone.
