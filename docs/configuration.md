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
calling and strict JSON Schema structured outputs. Run `skillroll doctor` from
the repository (or a nested directory) before the first eval; it finds the
nearest `skillroll.toml` automatically.

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

## Gateway-specific parameters

Some OpenAI-compatible gateways require extra request-level parameters — for
example, reasoning models that must receive `reasoning_effort = "none"` before
they will accept function tools. Pass these via `[inference.extra_body]`:

```toml
[inference]
base_url = "https://gateway.example/v1"
model    = "provider/model"
api_key_env = "SKILLROLL_API_KEY"

[inference.extra_body]
reasoning_effort = "none"
```

SkillRoll forwards every key/value pair here verbatim to the SDK's `extra_body`
kwarg on each completion call. Values must be JSON-serialisable scalars, lists,
or nested dicts (up to 4 levels). Keys that overlap with standard OpenAI
parameters (`model`, `messages`, `tools`, etc.) are rejected at config load
time. Omitting the section or leaving it empty sends no extra parameters.

## Choosing the endpoint

By default SkillRoll speaks Chat Completions. Some reasoning models reject
function tools on that endpoint unless reasoning is turned off, and accept them
only on `/v1/responses`. Select that endpoint with `wire`:

```toml
[inference]
base_url = "https://gateway.example/v1"
model    = "provider/reasoning-model"
api_key_env = "SKILLROLL_API_KEY"
wire     = "responses"

[inference.extra_body]
reasoning = { effort = "high" }
```

`wire` accepts `"chat_completions"` (the default) or `"responses"`; anything else
is rejected at config load time. The setting applies to every model call —
compatibility preflight, world simulation, judging, and the skill run itself — so
a provider that accepts one cannot be asked to serve the other. SkillRoll
translates the request for you: `messages` becomes `input`, `max_tokens` becomes
`max_output_tokens`, and a `response_format` becomes a `text.format` config.

## Models that reject temperature

SkillRoll asks for `temperature = 0` when it simulates the world and when it
judges, so those two stages stay as repeatable as the provider allows. Several
reasoning models reject the parameter outright and return a 400. Declare that
and SkillRoll leaves it out:

```toml
[inference]
base_url = "https://gateway.example/v1"
model    = "provider/reasoning-model"
api_key_env = "SKILLROLL_API_KEY"
supports_temperature = false
```

This is a property of the model, not of the endpoint: the same gateway usually
accepts `temperature` from a non-reasoning model on the very same `wire`. The
default is `true`, so a repository that does not set it keeps sending
temperature exactly as before.

## Reasoning models behind a gateway

A reasoning model that rejects both function tools on Chat Completions and the
`temperature` parameter (for example `example-reasoning-model` on an OpenAI-compatible
gateway) needs all three settings above together:

```toml
[inference]
base_url = "https://gateway.example/v1"
model    = "example-reasoning-model"
api_key_env = "SKILLROLL_API_KEY"
wire     = "responses"
supports_temperature = false

[inference.extra_body]
reasoning = { effort = "high" }
```

`wire = "responses"` lets function tools coexist with reasoning,
`supports_temperature = false` stops SkillRoll sending `temperature = 0` in
world simulation and judging, and `extra_body.reasoning` selects the effort. The
same settings reach compatibility preflight, the world simulator, the judge, and
the skill run. When a model leaks its native tool-call markup into the single
`world_action` tool, SkillRoll recovers the intended call on either wire and
records it in `transcript.jsonl` with `source` `recovered` (or `rejected` when
nothing can be recovered) instead of failing without a trace.

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
