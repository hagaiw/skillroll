# Configuration

Start with one named model. SkillRoll uses it to run the skill, play the
Dungeon Master, and judge the result.

```toml
[inference]
base_url = "https://provider.example/v1"
model = "provider/model-name"
api_key_env = "SKILLROLL_API_KEY"
```

The endpoint must provide an OpenAI-compatible Chat Completions API with tool
calling and strict JSON Schema structured outputs. Run
`skillroll doctor --repo PATH` before the first eval.

`SKILLROLL_API_KEY` is the provider-neutral default. `api_key_env` can name any
environment variable you already use. Keep the key itself in your shell or CI
secret store:

```shell
export SKILLROLL_API_KEY="your-key"
```

Use representative cases to choose the least expensive model that gives
stable, useful results. A model-backed run can include calls for the skill,
Dungeon Master actions, and the judge. Focused cases keep that work small
enough for regular prompt development and CI.

Free or changing routes are useful for checking endpoint wiring. Do not use
them to compare results over time because their model and capacity can change.

## OpenRouter

OpenRouter is optional. It offers many models through one compatible endpoint.
For ongoing evals, our current price/performance recommendation is
[`openai/gpt-5.6-luna-pro`](https://openrouter.ai/openai/gpt-5.6-luna-pro):

```toml
[inference]
base_url = "https://openrouter.ai/api/v1"
model = "openai/gpt-5.6-luna-pro"
api_key_env = "SKILLROLL_API_KEY"
```

`skillroll init --skills-path PATH --openrouter-free` configures OpenRouter's
changing free route for a setup sanity check. It is not suitable for regression
or release evidence.

## Optional model profiles

A profile lists models to try during setup for one purpose:

```toml
[inference]
base_url = "https://provider.example/v1"
api_key_env = "SKILLROLL_API_KEY"
default_profile = "authoring"

[inference.profiles.authoring]
purpose = "Normal authoring runs."
models = ["provider/primary", "provider/fallback"]
```

SkillRoll selects the first compatible model before the case starts. It then
uses that model for the whole case and never switches midway. Use
`--model-profile NAME` when no default is configured.

## Optional cost estimates

Add rates that you maintain yourself:

```toml
[pricing]
currency = "USD"

[pricing.models."provider/primary"]
input_per_million = 0.40
output_per_million = 1.60
```

`result.json` reports usage when the provider supplies it. SkillRoll estimates
cost only when it finds matching rates. Missing usage or pricing means the cost
is unavailable, not zero. SkillRoll does not fetch prices, so check the
provider's current rates before budgeting.
