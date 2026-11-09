---
name: run-blind-evals
description: Execute a frozen SkillRoll case pack with live inference, preserve its evidence, and classify technical, case-authoring, and target-skill outcomes.
---

# Run blind evals

Verify that target, SkillRoll, and case hashes match their preregistration.
Run offline validation, check the configured endpoint with `doctor`, and then
run every frozen case with live inference. Validation and `doctor` are setup
evidence; only completed model-backed evals test skill behavior.

Preserve each run ID, verdict, transcript, model, revisions, limits, and usage.
Keep `PASS`, behavioral `FAIL`, `ERROR`, and incomplete evidence distinct.
A timeout is a technical `ERROR`, even if it leaves no final response. Count
each timed-out attempt separately, including an unchanged retry.
In the final summary, preserve the numeric count of every outcome and state
whether a product control or other isolating evidence was run. Do not draw a
product conclusion without that evidence.
Include each case hash in the final run table and explicitly name requested
diagnostics such as controls or extra samples that were not run.
Correct and rerun a demonstrated case-authoring defect as a new, non-comparable
experiment. Preserve the original classification. For a behavioral failure,
report the result and explicitly record that the case, criteria, and target
skill were kept as supplied. Preserve the evidence without retrying for a pass.

When the request supplies completed run evidence for triage, classify that
evidence directly without enumerating the workspace or executing the cases
again. When execution is requested, use the frozen manifest paths rather than
searching unrelated files.

Read [run context](references/context.md) for classification and bounded reruns.
