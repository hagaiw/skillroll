# Changelog

Notable user-visible changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Generated GitHub workflows use the current checkout action and require an
  explicit repository variable before automatic live pull-request evaluation.

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

[Unreleased]: https://github.com/hagaiw/skillroll/compare/v0.1.0...HEAD
