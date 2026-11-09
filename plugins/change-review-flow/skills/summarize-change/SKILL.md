---
name: summarize-change
description: Use when supplied change evidence needs a bounded factual summary artifact.
---

# Summarize change

Extract only changed components and observable effects from the supplied
evidence. Mark any missing evidence as unknown. If the supplied description is
too sparse to identify a change or its effect, say so directly and ask for the
smallest evidence that would resolve the gap—for example, filenames or a diff
for what changed, and test results or observed behavior for its effect. Do not
fill gaps with likely configuration details or assumed outcomes. Return a short
summary artifact.

See [evidence context](references/context.md).
