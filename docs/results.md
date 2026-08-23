# Results and troubleshooting

SkillRoll keeps observed behavior separate from whether the harness completed
safely.

| Outcome | Meaning | First check |
| --- | --- | --- |
| `PASS` | All enabled expectations passed. | Confirm the case is realistic and specific. |
| `FAIL` | One or more expectations were not met. | Read `report.md` and the transcript. |
| `INCOMPLETE` | A required repository check was skipped. | Review the command before opting in. |
| `ERROR` | No trustworthy verdict could be produced. | Read the reported stage and cause. |

Offline `validate` reports blocking parse, selection, containment, and limit
problems separately from non-blocking advice.

## Evidence files

Completed live runs are private by default under
`.skillroll/runs/<run-id>/`:

- `report.md`: human-readable outcome and next action;
- `result.json`: canonical summary for automation;
- `transcript.jsonl`: ordered skill actions and World results;
- `inputs.json`: selected case hash and bounded input manifest;
- `execution.json`: final response and execution usage;
- `judge.json`: semantic decision and criterion evidence;
- `checks.json`: repository-check outcomes and bounded logs; and
- `verdict.json`: final outcome and safe failure details.

Samples and skill-omission controls write a parent record under
`.skillroll/experiments/`. Their comparison is authoring evidence, not another
verdict.

## Interpret the signal

A pass means this observed run met this case. Its value depends on a realistic
Input, coherent World behavior, meaningful skill-owned choices, and observable
criteria. Repeat important cases and pin the model when comparison matters.

Exact checks inspect final-response text. Transcript action names, arguments,
order, and count remain evidence for semantic judgment and diagnosis; they are
not exact assertion types.

`max_turns` counts model turns. Leave enough turns for a final response after
actions. `max_output_tokens` applies to execution, World simulation, and
semantic judgment. The repository default is 8,192. Use 4,096 for a short case
with one to three concise criteria; keep 8,192 for a moderate transcript; use
16,384 only for unusually large evidence or a model known to need it.

If the semantic judge reaches the output limit, the result is a technical
`ERROR`, not a skill `FAIL`. Preserve the original run and use the suggested
next tier for a non-scoring diagnostic. That diagnostic does not replace the
original result.

## Common problems

- **No cases found:** put cases under a skill's `evals/` directory and include
  `Input`, `World`, and `Success criteria`.
- **Endpoint configuration missing:** add `base_url`, `api_key_env`, and a
  model or profile, export the key, then run `doctor`.
- **Doctor fails:** check the HTTPS URL, model, key, tool calling, and strict
  JSON Schema support.
- **Turn limit reached:** inspect the transcript to decide whether the intended
  workflow needs another turn or the skill is looping.
- **Repository check incomplete:** review the exact command and rerun with
  `--run-commands` only when you trust its host-side effects.
- **Skill-omission control passes:** the Input may reveal the answer, the
  criteria may be broad, or general model behavior may be sufficient.
- **Cost missing:** providers do not always return usage, and estimates require
  matching user-supplied rates.
- **Evidence missing:** validation-only commands do not create live runs; for
  an eval, also confirm `.skillroll/runs/` is writable.

When asking for help, include the SkillRoll version, Python version, operating
system, command, and redacted diagnostic. Never include keys, provider headers,
private prompts, or unreviewed evidence. See [SUPPORT.md](../SUPPORT.md) and the
[security model](security.md).
