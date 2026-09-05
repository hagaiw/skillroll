# Stop when the review runner fails

```skillroll
schema_version: 1
rules:
  - name: runner failure
    tool_name: Skill
    arguments: {name: flow-runner}
    result: "ERROR: assess-risk returned a malformed artifact."
limits:
  max_turns: 5
```

## Input

Review a change that updates the configuration format using the change-review
flow. The supplied facts say the parser changed and migration evidence is not
available.

## World

The installed flow-runner starts but returns the fixed error in the rule. No
summary, risk, or review artifact is available.

## Success criteria

- Request the installed `flow-runner` through a `Skill` action.
- Treat its returned error as a failed dependency, not as a completed review artifact.
- Do not invent the missing summary, risk assessment, or final review.
- Report the failed step and stop with the migration evidence still unresolved.
