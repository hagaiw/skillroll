# Writing evals

One eval is one Markdown file beside a skill. It describes:

- `Input`: what the user asks;
- `World`: what is true outside the skill; and
- `Success criteria`: what good behavior looks like.

The Dungeon Master is a controlled simulator that plays the World. Whenever the
skill tries to use a tool, service, command, or other external capability, the
Dungeon Master returns a result that fits your description. You write the
situation, not a mock framework or a skill-specific test harness.

Keep each case under the selected skill's `evals/` directory and test one
important behavior.

## Start with a behavior

Create a case from the configured repository:

```shell
skillroll new my-skill wait-for-ci
```

When run from a nested directory, `new` walks up to the nearest
`skillroll.toml`, so the same command works there. Use `--repo PATH` when you
want to select a different repository explicitly.

SkillRoll creates `my-skill/evals/wait-for-ci.eval.md` without replacing
existing work. Fill its three sections:

```markdown
# Wait for required CI

~~~skillroll
schema_version: 1
~~~

## Input

Ship pull request 42 if it is ready.

## World

Pull request 42 is open. Its required build is still running. If the skill
checks the pull request or its CI status, return that state.

## Success criteria

- Check whether the required build has finished.
- Do not merge while it is still running.
- Tell the user what is blocking the merge.
```

`Input` is the request and context given to the skill. Keep it realistic. Do
not reveal the expected decision or answer just to make the case pass.

`World` is the Dungeon Master's brief. The skill cannot read it directly. It
learns about the World only through the results of its actions. The Dungeon
Master cannot access the real filesystem, shell, network, services, or other
skills.

`Success criteria` are observable outcomes. Write three to five when
possible, and allow equivalent wording and reasonable action choices. A
promise to act later is not completed work. Plausible code is not proof that
it runs.

For a text-only case, say that no external interaction is needed.

## Use the prompt development loop

Turn a prompt failure into a case before fixing it:

1. Preserve the real request in `Input`.
2. Describe only the external state needed for that behavior.
3. State the observable result you expected.
4. Confirm the case fails for the intended reason.
5. Fix the skill and run the case again.
6. Keep the case to catch the regression in future changes.

Validate the evals below your current directory before spending model calls,
then run the case and read the report:

```shell
skillroll validate
skillroll eval --case SKILL/evals/CASE.eval.md
```

`validate` finds the nearest `skillroll.toml`. Run it from the repository root
to validate every configured eval, from a skill directory to validate that
skill's evals, or use `--all` to request the whole repository explicitly.
Use `--case` when you need a single targeted check.

`eval` uses the same nearest-config lookup. A bare run evaluates cases below
the current directory; use `--all` to evaluate every configured case.

If the result is surprising, inspect the transcript. Change the skill when its
behavior is wrong. Change the case when its Input, World, or criteria do not
describe the intended behavior clearly.

## Simulated behavior and real checks

Use the Dungeon Master to test how a skill behaves around external
interactions. It can simulate a command result, a service response, a missing
file, a failure, or any other state the behavior needs.

Use a repository check or an external test only when you must prove that a real
command runs, an artifact is valid, or a real service changed. Repository
checks are ordinary host commands, not sandboxed operations. They run only with
`--run-commands`.

## Exact text and limits

Success criteria check meaning. Use an exact assertion only when the final
response must contain, omit, or equal literal text:

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

The supported assertions are `final_output_contains`,
`final_output_not_contains`, and `final_output_equals`. Use synthetic
canaries, never real credentials.

Put limits under the metadata block's `limits` mapping. `max_turns` counts
model turns, so leave one for the final response after any actions.
`max_output_tokens` applies to the skill run, Dungeon Master, and judge.
Raise a limit only when the intended behavior needs it.

SkillRoll warns when the selected `SKILL.md` is 128 KiB or larger, but it
continues the evaluation. Supporting files are indexed incrementally, so a
large reference or media file does not block the run. The `Read` action still
returns only UTF-8 files up to 64 KiB; larger files remain available for
identity and safety checks but are not placed in the model's action history.
The bundle still accepts at most 512 regular files.

Each simulated external action uses a model turn. Reserve one turn for the
skill's final response. If a case is about a decision process rather than the
contents of a repository or service, make it text-only instead of encouraging
irrelevant exploratory reads. Raise `max_turns` only when those actions are
part of the behavior being tested.

After adding cases, confirm they appear in version-control status. A broad
repository rule such as `evals/` can hide every SkillRoll case; validation warns
about that common rule, but Git remains the authority for more complex ignore
patterns.

For an important case, run independent samples. You can also run the same case
without the skill:

```shell
skillroll eval --case CASE --samples 3 --with-skill-control
```

That comparison is a diagnostic, not another gate. If both variants pass, the
Input may reveal the answer, the criteria may be too broad, or the base model
may already provide the behavior. See [Results](results.md) for diagnosis.
