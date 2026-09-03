# Decision map

Complete this small map before authoring a new case. It keeps a missing fact or
ordinary software defect from being mislabeled as a prompt failure.

| Locus | Question | Route |
| --- | --- | --- |
| `context gap` | Is a fact, source, permission, or prerequisite absent? | Supply neutral context, obtain the source, or defer. The absence alone is not a skill failure. |
| `deterministic defect` | Does a parser, script, command, or state transition return the wrong result even without the skill? | Add or fix an ordinary unit, integration, or state-transition test. Test the skill's reaction separately if that reaction is the judgment seam. |
| model judgment seam | With the relevant state and evidence present, must the skill interpret ambiguity, authority, confidence, provenance, ownership, or completion and choose a material branch? | Write a focused SkillRoll case when the World can expose the consequence. |

For each serious candidate, record:

```markdown
### <behavior>

- Locus and route:
- Evidence already available:
- Trigger and state immediately before the choice:
- Judgment the skill owns:
- Material safe and unsafe branches:
- Governing skill instruction:
- Consequence and reversibility:
- Observable oracle:
- Deterministic prerequisites to hold fixed:
- Context prerequisites to supply:
- Existing coverage and gap:
```

Rank only a few candidates using consequence, plausibility, skill-specific
causality, testability, repairability, and information value. Select the
highest-value model judgment seam whose action or claim can actually be
observed. Resolve a `context gap` or `deterministic defect` before spending
live inference; neither is a prompt failure by itself. Mark unknowns as
unknown; do not fill a missing prerequisite with an assumption.
