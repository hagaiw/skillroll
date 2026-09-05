# Author one ordinary single-skill case

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 180
  max_output_tokens: 8192
```

## Input

I’m reviewing this small skill outside its repository. Its relevant text is:

### incident-summary/SKILL.md

- Use the supplied incident timeline to produce a concise status summary.
- Keep claims tied to observed events.
- If the timeline does not establish a cause, report the cause as unknown rather
  than inferring one.

Please draft one SkillRoll case for this skill for maintainer review. Include a
short rationale for why the case is useful. Do not edit files, run commands, or
use model inference.

## World

No external interaction is needed. The supplied skill text and request are
sufficient to draft a self-contained scenario. The candidate case may introduce
a realistic partial timeline in its World, but must not put the causal conclusion
in its Input.

## Success criteria

- Produce one complete case using SkillRoll’s supported schema, Input, World,
  and Success criteria sections.
- Give the candidate case a natural user request without stating the expected
  answer or workflow.
- Give the candidate Input only observed events, their temporal relationship,
  and a natural request to summarize or assess the incident. Do not state there
  that the cause is unknown, unconfirmed, unsupported, or still under
  investigation.
- Put the absence of causal evidence in the candidate World, rather than
  assuming the evaluated agent already knows that conclusion.
- Test the single distinction between observed events and unsupported causal
  claims with semantic criteria, not exact wording.
- Describe the result as an offline draft and make no claim that a file, command,
  or model run was completed.
