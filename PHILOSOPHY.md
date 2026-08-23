# The skillroll philosophy

- Prompts, like code, should have tests.
- Evals that are hard to write, are not written.
- 

- A failing eval should precede a prompt fix.
- Verified change is better than hopeful change.
- Errors and outputs should be actionable and simple to read with no previous knowledge or context.
- Lllms are non deterministic, we can't properly evaluate prompts using deterministic tests.
- Context should not be evaluated.
- Deterministic parts of a skill should be tested with detemrinistic tests.
- a skill with a clean seperation of concerns (agentic/non-deterministic, scripts/deterministic, context/knowledge) is easier to maintain and evaluate
- a simple skill with one clear goal is easier to maintain and evaluate than a complex monstrosity.

- skillroll's power is in it's simplicty, simple to setup, simple to run, simple to write evals
- the dungeoun master harness allows for simple yet powerful evals, because stories are easy to read and write.
- the dm tool is powerful because it can simulate basically anything with very little text, because it replicates how agents see the world, via their textual context history.

- an error people learn to ignore is worse than a meaningful warning
- errors and warnings should be easy to act upon, we never throw error codes and context-less erros ar the user


- One eval should test one important behavior.
- One skill should do one thing well.
- Separate concerns: judgment in skills, certainty in scripts, knowledge in references.
- Complex behavior should comes from composition, not from growing a monster single prompt.

- Every artifact should explain itself.
- Coverage should be readable/reviewable, not merely plentiful.
- An honest “cannot evaluate this well” beats a rubber stamp.

- Advanced rigor should be a path, not an entrance fee.
- Practical protection beats theoretical completeness.

- SkillRoll should catch regressions in nondeterministic skills.
- It is a drop in framework that requires nothing but an api key.

- Every change must preserve these principles.
- If it cannot, the change can't be merged, or the philosophy need to be updated.
