# Semantic judge prompt context

This reference explains the internal `semantic-judge-prompt` dogfood skill
under `plugins/harness-prompts/skills/semantic-judge-prompt/`. The judge is
called only after execution and receives evidence assembled by SkillRoll. Its
decision is semantic evidence, not a deterministic proof; exact final-output
facts and trusted repository checks remain separate checks.

Completed evidence is literal. A future promise, offered next action, implied
path or timestamp, or a judge-supplied reconstruction does not satisfy work the
case requires now. When the final output or transcript contradicts an evidence
claim, the contradiction controls. The judge also does not repair or validate
executable code, configuration, commands, or artifacts in its reasoning; use a
trusted deterministic check or external integration evidence for that claim.

The judge audits factual claims against Input and completed action results
before assessing criteria. Timing, quantity, cause, and attribution are facts,
not harmless prose. If an unsupported modifier is used to establish a
criterion, that criterion is not met. This audit does not create a new generic
criterion: an unsupported detail unrelated to the authored behavior may be
identified in the rationale without changing otherwise supported statuses.

The runtime loads the packaged system resource from this skill's prompt
contract. Dynamic evidence framing in `src/skillroll/judge.py` stays in code
because it serializes the current case and transcript. Eval metadata is not
included in that evidence beyond the authored Success criteria.

The labeled final response remains observed evidence when no action occurred.
“No completed actions” must never be expanded into “no final output” when the
Final output section contains text.

The dogfood skill is instruction-only. The evaluated actor applies the contract
itself; it never asks World or a named action to perform semantic judgment.
World-model prose cannot substitute for inspecting the supplied evidence.
