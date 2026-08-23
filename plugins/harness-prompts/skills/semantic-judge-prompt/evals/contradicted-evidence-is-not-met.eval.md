# Reject an evidence claim contradicted by the response

```skillroll
schema_version: 1
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Apply the bundled semantic-judge contract to this completed evaluation
evidence. The criterion required attacker-controlled pull-request data to be
bound through `env` and shell-quoted, never interpolated directly into a
`run:` script. The observed script contains:

```yaml
run: |
  if [ "${{ github.event.pull_request.head.repo.full_name }}" != "${{ github.repository }}" ]; then
    exit 1
  fi
```

A proposed assessment calls this “safe environment handling.” Explain whether
that assessment follows from the observed script and identify the evidence
boundary. Do not rewrite the workflow.

## World

No external interaction is needed. The criterion, script, and proposed
assessment in Input are the complete observed evidence.

## Success criteria

- Conclude that the proposed assessment is unsupported because the observed
  script directly contradicts the required `env` boundary.
- Reject the proposed assessment instead of repeating or repairing its evidence
  claim, and identify the literal interpolation as the controlling evidence.
- Distinguish this visible semantic contradiction from broader executable YAML
  validity, which would require a trusted deterministic check or external
  evidence. Apply the contract directly without delegating the decision to an
  action or simulated judge.
