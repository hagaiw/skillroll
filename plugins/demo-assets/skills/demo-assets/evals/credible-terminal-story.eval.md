# Tell one credible terminal story

```skillroll
schema_version: 1
limits:
  max_turns: 4
  timeout_seconds: 90
  max_output_tokens: 1400
```

## Input

Improve our developer tool's README demo. The current animation spends time on
API setup, jumps between slides, and ends with “your workflow is protected” even
though the CLI never prints that. The real commands support creating an eval,
editing its Markdown, running one case, printing a one-sentence judge rationale,
and linking the report. Propose a short terminal story and explain what should
be rendered versus taken from real product behavior.

## World

No external interaction is needed. The Input contains the complete product and
demo constraints.

## Success criteria

- Propose one continuous, relatable create → edit → run terminal story with a
  visible payoff in the final terminal frame.
- Remove setup and credentials from the story and do not invent product output
  such as “your workflow is protected.”
- Distinguish real commands and CLI wording from illustrative model results,
  identifiers, typing, pauses, and editor rendering.
- Recommend keeping deterministic rendering in scripts and inspecting the
  generated animation for timing and legibility.
