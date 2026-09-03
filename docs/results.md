# Results and troubleshooting

Read `report.md` first. It states the outcome, summarizes the evidence, and
suggests what to check next.

| Outcome | Meaning | First check |
| --- | --- | --- |
| `PASS` | The observed behavior met every enabled expectation. | Confirm the case is realistic and specific. |
| `FAIL` | One or more expectations were not met. | Read the report and transcript. |
| `INCOMPLETE` | A required repository check was skipped. | Review the command before opting in. |
| `ERROR` | SkillRoll could not produce a trustworthy verdict. | Read the reported stage and cause. |

A pass means one observed run met one case. Repeat important cases and use a
named model when results need to be compared.

Offline `validate` finds case structure, selection, containment, and limit
problems without calling a model.

## Read the evidence

Model-backed runs are private by default under `.skillroll/runs/<run-id>/`.
The main files are:

- `report.md`: the result for a person to read;
- `transcript.jsonl`: completed World actions and the Dungeon Master's replies;
- `execution.json`: the final response, usage, and any attempted tool calls; and
- `result.json`: the result for automation.

The transcript records only actions that reached the World. If a run produces
final execution facts but then hits an execution boundary, `execution.json`
retains the reported final response and attempted calls while the judge and
repository checks remain unrun. The same directory also preserves the selected
inputs, judge decision, repository checks, and final verdict as JSON. Together
they show what ran and why SkillRoll reached its outcome.

Sampled runs and no-skill comparisons live under
`.skillroll/experiments/`. Their comparison helps diagnose a case; it is not a
second verdict.

## Fix a failed case

Start with the report, then inspect the transcript:

1. If the skill made the wrong choice, fix the skill and rerun the case.
2. If the request was unrealistic, fix `Input`.
3. If the Dungeon Master returned the wrong situation, fix `World`.
4. If good behavior could not satisfy the case, fix `Success criteria`.
5. If the run failed technically, fix the reported stage before judging the
   skill.

Exact assertions inspect final-response text. The judge uses the final response
and completed action transcript to check the meaning of each success criterion.

`max_turns` counts model turns. Leave enough turns for a final response after
the skill's actions. `max_output_tokens` applies to the skill run, Dungeon
Master, and judge. If the judge reaches that limit, the outcome is `ERROR`, not
`FAIL`. Preserve the original result and use the suggested higher limit only
as a non-scoring diagnostic.

## Common problems

- **No cases found:** put cases under a skill's `evals/` directory and include
  `Input`, `World`, and `Success criteria`.
- **Endpoint configuration missing:** add `base_url`, `api_key_env`, and a
  model or profile, export the key, then run `doctor`.
- **Doctor fails:** check the HTTPS URL, model, key, tool calling, and strict
  JSON Schema support.
- **Turn limit reached:** check whether the intended behavior needs another
  turn or the skill is looping.
- **Repository check incomplete:** review the command and rerun with
  `--run-commands` only when you trust its effects.
- **No-skill comparison passes:** the Input may reveal the answer, the
  criteria may be broad, or the model may provide the behavior without the
  skill.
- **Cost missing:** the provider may not return usage, or your configuration
  may not include a matching rate.
- **Evidence missing:** `validate` does not create a model-backed run. For
  `eval`, also confirm `.skillroll/runs/` is writable.

When asking for help, include the SkillRoll version, Python version, operating
system, command, and redacted diagnostic. Never include keys, provider headers,
private prompts, or unreviewed evidence. See
[SUPPORT.md](../.github/SUPPORT.md) and the
[security model](security.md).
