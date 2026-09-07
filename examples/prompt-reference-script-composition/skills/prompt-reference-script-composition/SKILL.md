---
name: prompt-reference-script-composition
description: Compose evidence-grounded customer notes while routing audience policy to a reference and repeated heading formatting to a deterministic script.
---

# Compose a customer note

Draft the note from the user's request and supplied evidence. Keep content
choices, audience judgment, and factual claims in the prompt workflow.

1. Read the [audience policy](references/audience-policy.md) when the
   recipient's terminology or tone needs a conditional choice.
2. Decide the note's content and claims from the supplied evidence before
   formatting it.
3. Use the [heading normalizer](scripts/normalize-headings.py) for repeated
   Markdown heading formatting when a real script execution is available. The
   script changes heading syntax only; it does not select content or add facts.
4. Keep an unresolved fact unresolved, and never claim that a script or an
   external action ran unless its result is actually observed.
