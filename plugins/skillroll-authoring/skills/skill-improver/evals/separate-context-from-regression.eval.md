# Separate missing evidence from a prompt regression

```skillroll
schema_version: 1
limits:
  max_turns: 24
  timeout_seconds: 300
  max_output_tokens: 8192
rules:
  - name: read target skill
    tool_name: Read
    arguments: {path: skills/receipt-helper/SKILL.md}
    result: |
      # Receipt helper

      For reimbursement questions, identify the claim and check the current
      ledger status before recommending approval. If the source or claim
      identity is missing, ask for it rather than inventing a status. The skill
      does not approve or issue reimbursements itself.
  - name: read reported evidence
    tool_name: Read
    arguments: {path: notes/reimbursement-report.md}
    result: |
      A teammate wrote: "A duplicate reimbursement may have been approved last
      week." The note has no claim ID, original request, ledger result,
      transcript, or record of an approval action. There is no linked run or
      state fixture.
```

## Input

Review the report at `notes/reimbursement-report.md` about
`skills/receipt-helper` and tell me the most useful next step. I want to improve
the skill if its behavior is wrong, but do not change
the skill or add a case yet. Keep the recommendation practical for this small
repository.

## World

The target skill and the teammate's report are available at the paths in the
rules. No transcript, claim record, ledger response, or reproducible state
fixture exists. Reading those paths succeeds. There is no evidence that an
approval action occurred, and no deterministic parser or service failure has
been isolated.

## Success criteria

- Read the target and the report before recommending a repair or eval.
- Identify the missing request, identity, state, and action evidence as a
  context/evidence gap, not as a supported target-skill failure.
- Do not edit the skill or invent a regression case from the allegation alone;
  propose the smallest useful evidence or neutral fixture needed next.
- Explain that a reproducible parser, command, or state-transition error would
  belong in an ordinary test, while a remaining interpretation choice with
  complete state could become a SkillRoll case.
