# World-backed case design

The selected decision-map row is the case contract. Keep setup that is not
under test out of the agent's work so the case reaches the real choice.

## Input

Write the ordinary request at the decision point. Include the user's goal and
constraints, but do not name the suspected bug, mention the eval, or prescribe
the safe answer. Supply facts that a real user or main session would already
know in `Input`; do not hide necessary context in `World`.

## World

Describe a non-empty external state and only the action consequences needed for
the decision. For filesystem, service, Git, authentication, or other stateful
behavior, prefer a deterministic fixture or exact rule. Keep names neutral so
filenames and returned values do not reveal the oracle. A rule must match the
action name and complete argument structure; if an equivalent action misses
that rule, treat the run as a case/World mismatch rather than silently calling
it proof.

The World is not visible to the evaluated skill. It learns those facts through
its available action boundary. Never require a real command, service change,
compiled artifact, or visual result from a simulated response; use a trusted
check or external test for that claim.

## Success criteria

Tie each criterion to the mapped decision and an observable response or action.
Allow equivalent safe methods, clarification, stopping, escalation, and
uncertainty disclosures where they genuinely preserve the boundary. Do not
require a fixed sentence, exact command spelling, exhaustive list, or a final
claim that is unsupported by the transcript. Distinguish an action that was
never attempted from one that was attempted and later undone.

Before inference, run:

```shell
skillroll validate --case path/to/case.eval.md
```

Use enough `max_turns` for required actions and a final response, and enough
`max_output_tokens` for the judge. Change one case dimension at a time. Never
overwrite the only copy of a case after it has been run; snapshot a revision,
record its new hash, and explain whether the change addressed Input, World,
limits, or scoring.
