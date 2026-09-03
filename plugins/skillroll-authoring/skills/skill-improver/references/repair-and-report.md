# Repair, regression, and evidence

## Maturity labels

- **Drafted:** the case passed offline validation.
- **Exercised:** a complete live run was inspected.

## Primary classification

After reviewing the available evidence, assign exactly one primary
classification:

- `context gap`: a required fact, source, permission, or prerequisite was
  missing; route it to context or evidence work before live inference.
- `deterministic defect`: a parser, script, command, or state transition is
  wrong independently of the skill; route it to an ordinary test or fix.
- `supported strength`: the skill handled a fair case safely.
- `supported skill failure`: a fair case showed the skill taking the wrong
  consequential action or making an unsupported claim.
- `case defect`: Input, World, criteria, or limits could not fairly test the
  intended decision.
- `World/harness defect`: the simulator, action boundary, or evidence was
  contradictory or misleading.
- `judge defect`: the label conflicts with grounded transcript evidence.
- `technical inconclusive`: provider, parsing, timeout, or evidence machinery
  blocked a behavioral verdict.

## Run and review

For an authorized live check, run the validated case once before a batch. Read
the full transcript and artifacts. Confirm that the promised World facts were
returned, the intended skill bundle was loaded, the action consequence is
present, and the semantic verdict agrees with the evidence. A no-skill control
or additional samples is diagnostic; it does not silently replace the main
case or require the control to fail.

Use `supported strength` for a complete run that met the observable criteria;
do not treat an automatic verdict as a substitute for this review.

An `ERROR` is not a behavioral `FAIL`. Retry an unchanged technical error only
when it could be transient and authorization allows it; preserve both runs.

## Repair and nearby checks

Only a reviewed supported skill failure justifies a prompt fix. Change the
narrowest instruction at the decision point, preserving the skill's purpose
and voice. Then:

1. validate the unchanged final case;
2. run that identical case after the repair and compare its hash;
3. inspect the repaired transcript and result;
4. run nearby cases that cover the same instruction's safe path or a likely
   boundary; and
5. keep all original and repaired artifacts, including usage and missing data.

If the case or World was defective, repair the experiment instead and do not
rewrite the skill. If the problem is deterministic, add the ordinary test and
keep any separate judgment case narrow.

## Bounded report

State the target and behavior, case paths and hashes, source and repaired skill
state, commands, requested and served models when available, run IDs, sample
counts, usage, classifications, and files changed. Say what did not run and
what remains uncertain. A finite repaired sample supports that case and those
conditions; it does not prove that the skill is universally safe.
