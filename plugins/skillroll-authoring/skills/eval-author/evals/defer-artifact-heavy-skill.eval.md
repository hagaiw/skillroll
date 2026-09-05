# Defer a skill whose outcome is an external artifact

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Add a meaningful SkillRoll eval for the `skills/document-renderer` skill if
the harness can test what matters. If it cannot, leave the skill without a
misleading eval and tell me what evidence should cover the missing behavior.
Keep the skill instructions unchanged.

## World

`skills/document-renderer/SKILL.md` instructs an agent to turn a Markdown
document into a PDF, choose page layout, run the repository's renderer, and
inspect the rendered pages for clipped text, missing images, and broken page
breaks. The important outcome is the visual PDF artifact. SkillRoll can judge
the agent's explanation or decision in a simulated case, but this task has no
trusted renderer check, PDF fixture, image comparison, or human visual review
available. No inference run is authorized.

## Success criteria

- Do not create a behavioral eval that claims to verify the PDF's visual
  layout, renderer execution, image comparison, or other unavailable artifact
  evidence.
- Explain that the skill is an external-evidence-needed or partial-fit case,
  and identify the exact behavior that remains outside this harness.
- If proposing a narrow case, limit it to a clearly skill-owned decision that
  does not imply the PDF was rendered or inspected; otherwise recommend no
  case and name an appropriate render-and-inspect test or manual review.
- Report the decision as a deliberate deferral, not as missing coverage to be
  filled with a placeholder, and keep the `SKILL.md` unchanged.
