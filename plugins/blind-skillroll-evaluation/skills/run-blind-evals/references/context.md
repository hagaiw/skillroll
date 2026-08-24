# Live-run context

Live inference is the primary signal. Require explicit authorization, a named
model and endpoint, and a key supplied only through the configured environment
variable. Do not put credentials in commands, configuration, artifacts, or
candidate-visible environments. Keep calls, samples, turns, tokens, and retries
within the authorized bounds.

Run frozen cases in stable order and do not drop one after observing another's
result. A no-skill comparison or extra samples are diagnostics, not silent
additional gates.

## Classify from evidence

- `PASS`: a complete live run satisfies the authored behavior.
- `TARGET_BEHAVIOR`: a valid, realistic case completed and the target skill
  missed one or more criteria.
- `CASE_AUTHORING`: Input, World, criteria, path, or metadata did not express a
  fair self-contained experiment.
- `PRODUCT`: SkillRoll itself failed and the evidence isolates that failure,
  preferably with a known-good control.
- `PROVIDER_ENVIRONMENT`: transport, compatibility, credential, rate, or model
  failure prevented a behavioral verdict.
- `UNRESOLVED`: available evidence cannot distinguish the cause.

An `ERROR` is not a behavioral `FAIL`. A timeout stays technical unless a
complete result proves otherwise.

Preserve every artifact. One unchanged retry is reasonable only for a plausibly
transient technical error and only within authorization. Correcting an
authoring defect or changing a case, model, limit, endpoint, or revision creates
a distinct non-comparable run. Report both the original and the new result.
