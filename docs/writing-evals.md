# Writing evals

An eval case is a realistic request, a controlled external situation, and a
short description of success. Keep each case under the selected skill's
`evals/` directory and test one important behavior.

Create one named template from the configured repository root:

```shell
skillroll new my-skill/important-behavior
```

SkillRoll creates `my-skill/evals/important-behavior.eval.md` without replacing
existing work. Open that file in your usual editor and fill its three sections.

```markdown
# Summarize an incident

~~~skillroll
schema_version: 1
~~~

## Input

Turn these notes into a short handoff: "The queue recovered after the restart.
We still need to inspect timeouts."

## World

The notes are the only external context. No files or services are available.

## Success criteria

- State that the queue recovered.
- Identify timeout inspection as the next step.
- Do not invent a root cause.
```

## Write the three sections

`Input` is what the skill receives: the user's request and context already
available to the session. Keep it realistic. Do not include the expected
decision or answer wording merely to make the case pass.

`World` defines simulated external state and action results. The skill cannot
read it directly; it learns World facts only from returned `world_action`
results. Skill-local text files can be served from the bounded skill bundle,
but the simulator cannot access the real filesystem, shell, network, services,
or other skills.

For a text-only case, say that no external interaction is needed. If the
behavior depends on a real command, service, binary artifact, host trigger, or
multi-agent workflow, use a trusted repository check or an external test.

`Success criteria` should contain three to five observable outcomes. Accept
equivalent wording and reasonable action choices. A promise to do work later
is not completed evidence, and plausible code is not proof that it runs.

## Choose the evidence

Use success criteria for meaning, judgment, equivalent wording, and reasonable
action choices. Use exact checks only when a literal must or must not appear in
the final response:

```markdown
~~~skillroll
schema_version: 1
limits:
  max_turns: 4
  timeout_seconds: 90
  max_output_tokens: 4096
assertions:
  - final_output_not_contains: "SYNTHETIC_SECRET_123"
~~~
```

Supported exact checks are `final_output_contains`,
`final_output_not_contains`, and `final_output_equals`. Use synthetic canaries,
never real credentials.

Trusted repository checks can verify syntax, tests, or artifacts. They are
ordinary host commands, not sandboxed operations, and run only with
`--run-commands`. Do not use semantic criteria to claim deterministic validity.

Limits belong under the metadata block's `limits` mapping; they are not valid
top-level metadata keys. `max_turns` counts model turns, so leave one for the
final response after any actions. `max_output_tokens` also applies to the
model-backed World and semantic judge, not only the final response. Raise a
limit only when the intended workflow needs it.

## Validate and improve

Validate before spending inference, then run one case and read its report:

```shell
skillroll validate --repo PATH --case SKILL/evals/CASE.eval.md
skillroll eval --repo PATH --case SKILL/evals/CASE.eval.md
```

Fix the smallest responsible part: the skill, case, model configuration, or
deterministic check. For a prompt regression, preserve the original request as
a case and confirm the old behavior fails for the intended reason before
editing `SKILL.md`.

When a case matters, collect independent samples and optionally compare it
with the selected skill omitted:

```shell
skillroll eval --repo PATH --case CASE --samples 3 --with-skill-control
```

The omission control is diagnostic, not another gate. If both variants pass,
general model behavior or an overly broad case may be carrying the result. See
[Results](results.md) for limits and diagnosis.
