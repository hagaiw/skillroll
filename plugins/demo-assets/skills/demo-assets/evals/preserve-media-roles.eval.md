# Preserve distinct README and terminal mascots

```skillroll
schema_version: 1
limits:
  max_turns: 4
  timeout_seconds: 90
  max_output_tokens: 1400
```

## Input

We have selected a detailed full-body mascot PNG for the GitHub README and a
tighter pixel-art closeup for ANSI output during interactive setup. A second
closeup was tested but is less appealing. Explain how to regenerate and verify
the chosen terminal asset without replacing the README mascot or the rejected
comparison files. The repository includes focused mascot-preparation and Chafa
rendering scripts.

## World

No external interaction is needed. The two selected source roles and the
available deterministic scripts are complete.

## Success criteria

- Keep the original full-body README source and closeup ANSI source as distinct
  assets, without promoting or deleting the rejected comparison.
- Use the mascot-preparation script for crop/contrast work and the ANSI renderer
  for Chafa conversion instead of embedding image manipulation in instructions.
- Preview the ANSI output in a compatible terminal and inspect repository status
  before replacing the packaged setup mascot.
- Do not upload, publish, install tools, or overwrite user-provided source art
  without explicit authorization.
