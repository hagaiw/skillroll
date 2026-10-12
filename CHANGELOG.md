# Changelog

Notable user-visible changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `[inference.extra_body]` TOML table: key/value pairs forwarded to the
  OpenAI-compatible SDK's `extra_body=` kwarg on every completion call.
  Useful for reasoning models that require gateway-specific parameters (e.g.
  `reasoning_effort = "none"`) before they accept function tools.
- `inference.wire` setting, either `"chat_completions"` (the default, unchanged
  behaviour) or `"responses"`. On `"responses"` SkillRoll talks to
  `/v1/responses` for compatibility, world simulation and judging, and executes
  the skill through the Agents SDK's `OpenAIResponsesModel`. Some reasoning
  models refuse function tools on Chat Completions unless reasoning is disabled
  and accept them only on Responses, so this keeps reasoning available.
- `inference.supports_temperature` setting, default `true` (unchanged
  behaviour). Set it to `false` for a model that rejects `temperature`
  outright — several reasoning models do — and SkillRoll omits the parameter
  from world simulation and judging instead of failing the run.

### Fixed

- `world_action` now recovers string-encoded `arguments` and leaked
  `<parameter>` tool-call markup instead of failing with a generic SDK error,
  returns a specific error for input it cannot recover, and records both cases
  in `transcript.jsonl` with `source` `recovered` or `rejected`.
  The decoder applies on both the Chat Completions and Responses wires.
- Execution usage read cached input tokens from `input_token_details`, but the
  Agents SDK names the field `input_tokens_details`, so `cache_read_tokens`
  was always empty and cached input was priced as fresh input. It now reads the
  real field.

## [0.1.2] - 2026-08-23

### Changed

- Simplified setup and project messaging around Markdown evals, Dungeon Master
  simulation, provider-neutral model configuration, and prompt TDD.
- Made OpenRouter Free an explicit setup check and documented Luna Pro as the
  current OpenRouter recommendation for ongoing evals.
- Moved GitHub community-health policies under `.github/` and renamed the
  project philosophy to `PRINCIPLES.md`.

## [0.1.1] - 2026-08-23

### Fixed

- Flow runner now executes each named skill step separately and combines the
  returned evidence instead of stopping after a plan or malformed action.

### Changed

- Generated GitHub workflows use the current checkout action and require an
  explicit repository variable before automatic live pull-request evaluation.
- Live evaluation jobs use a dedicated GitHub environment so access to the
  inference secret can require approval.

## [0.1.0] - 2026-08-23

Initial public release.

### Added

- Named inference profiles with preflight-only fallback, usage reporting, and
  optional user-supplied cost estimates.
- Optional independent samples and a non-gating skill-omission control for eval
  authoring.
- Exact `final_output_not_contains` checks for synthetic forbidden literals.
- Criterion-level semantic evidence in version 2 result files.
- A provider-specific library helper for retrieving authoritative OpenRouter
  generation cost after one completion.

### Changed

- Skill bundles exclude eval content, hidden paths, bytecode, and common
  generated or dependency directories.
- Offline validation distinguishes blocking safety/parse errors from advice.
- Reports distinguish behavioral `FAIL`, technical `ERROR`, and intentionally
  unrun `INCOMPLETE` outcomes.
- Public documentation is consolidated around the current product, and
  historical development records are no longer tracked in the repository.

[Unreleased]: https://github.com/hagaiw/skillroll/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/hagaiw/skillroll/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/hagaiw/skillroll/compare/v0.1.0...v0.1.1
