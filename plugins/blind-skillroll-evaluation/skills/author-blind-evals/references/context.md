# Blind authoring context

The author may inspect the selected `SKILL.md`, directly linked references, and
repository instructions needed to understand the skill. That is not outcome
leakage. Keep these materials out of the authoring context:

- earlier SkillRoll verdicts, transcripts, and report filenames;
- suspected bugs or desired pass/fail outcomes;
- baseline or no-skill responses; and
- private success criteria disguised as user instructions.

Use a fresh worker or context per target when the platform supports it. Give the
worker only the pinned preparation manifest and permitted source paths.

Every case is Markdown at `<skill>/evals/<scenario>.eval.md`:

````markdown
# Scenario title

```skillroll
schema_version: 1
```

## Input

<realistic request>

## World

<private external facts and simulated action results>

## Success criteria

- <observable behavior allowing equivalent wording or actions>
````

## Freeze a small pack

Prefer one case per distinct behavior and no more than two initial cases per
skill. Input must resemble a real request and must not reveal the answer. World
prose is evaluator-only; the evaluated skill learns external facts through
actions. Criteria should be supported by final-output or transcript evidence.

For a boundary case, distinguish facts supplied in Input or the skill, facts
discoverable through World actions, and facts or capabilities that remain
unavailable. Define material absence, failure, or conflict semantics without
turning a structural prompt concern into a predetermined behavioral verdict.

Run offline validation, then record each `.eval.md` path and content hash in a
case manifest. Unchanged starter text, missing sections, invalid metadata, or an
external scenario fact needed by the case but absent from realistic Input or
World blocks the live run. A skill-owned expectation may come from the selected
`SKILL.md`. Artifact rendering, real repository commands, and real service
changes need their own evidence and should not be claimed by a semantic case.
