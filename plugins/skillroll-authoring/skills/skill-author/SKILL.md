---
name: skill-author
description: Use when an author needs to create, review, audit, or improve an Agent Skill and its supporting references or scripts.
---

# Author Agent Skills

Create a skill that improves one coherent kind of work without constraining
unrelated requests. Start from the user's intended outcome and the decisions a
capable agent would not reliably make without added guidance.

## Audit a skill

Work directly from skill text, excerpts, and concrete facts the user supplies.
Read a target file only when its content is needed and its path is available;
never invent a path or delay a bounded review merely to request material already
present. If the missing content prevents the requested work, name that gap and
ask for it.

An audit is not automatically a rewrite request. For each structural finding,
return:

1. the implicated guidance and plausible observable risk;
2. the evidence status and a focused realistic eval that could test the risk;
3. only then, a possible localized repair if the evidence supports one.

Do not claim a behavioral violation without a completed realistic run. Place
any supported repair beside the capability or decision it governs rather than
adding a detached override.

## Author or improve a skill

Keep discovery precise: use a concise name and a description that says what the
skill does and when it applies. Put essential routing, consequential boundaries,
and the normal workflow in `SKILL.md`. Move substantial conditional knowledge
to linked references and repeated deterministic operations to scripts.

Match specificity to risk. State exact permission, safety, evidence, interface,
and stop requirements when deviation has a concrete cost. Otherwise specify the
outcome and decision criteria rather than one mandatory choreography. Preserve
the user's scope and do not treat task authorization as permission for unrelated
external effects.

Read [skill authoring context](references/context.md) for the canonical quality
standard, audit questions, repair method, and validation boundary.

When improving an existing skill, distinguish a structural concern from an
observed behavioral failure. Integrate the smallest supported repair into the
responsible section and surrounding vocabulary. Validate structure and scripts;
use a realistic behavioral eval when the claim is about model behavior.
