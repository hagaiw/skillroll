---
name: skill-improver
description: Use when a repository owner wants to improve an existing Agent Skill's behavioral reliability and regression coverage through SkillRoll; not for initial setup or generic eval-only authoring.
---

# Improve an existing skill

Use this skill when a repository owner wants to make an existing Agent Skill
more reliable and leave behind a useful regression check. Keep the work about
the selected skill and its observable behavior. It does not set up SkillRoll,
discover targets, rank popularity, run third-party campaigns, scout by history,
or publish a pull request.

## Workflow

1. Read the repository instructions, the target `SKILL.md`, its directly linked
   references, existing evals, and relevant ordinary tests. State the one
   behavior being improved and what evidence is already available.
2. Map the important decision before writing a case. Separate:
   - a **context gap**, where a needed fact, source, permission, or prerequisite
     is missing;
   - a **deterministic defect**, where a parser, script, command, or state
     transition is wrong; and
   - a **model judgment seam**, where the skill must interpret supplied state
     and choose between materially different actions, claims, or branches.
   Route the first two to better context or ordinary tests before live
   inference. When reporting a context gap, briefly say that an independently
   reproducible parser, command, or state-transition problem belongs in an
   ordinary test, while SkillRoll is for a fully evidenced model-judgment
   decision. Use SkillRoll for the last one.
3. Compare that map with current coverage and choose one meaningful uncovered
   decision. Do not add a placeholder case just to increase the count.
4. Before writing, verify that the candidate eval contains a realistic,
   neutral `Input`, a non-empty `World` stating the relevant state and the
   explicit material consequence of acting, and observable criteria. Author
   the regression case before changing the prompt, keep evaluator-only facts
   in `World`, and make the action consequence observable. Use one case for
   one behavior and accept equivalent safe actions or wording.
5. Run `skillroll validate` before inference. Run a live baseline only when the
   user or repository workflow has authorized it. Inspect the complete
   transcript, World results, criteria evidence, diagnostics, and usage; an
   offline-valid case is not evidence that the skill behaves correctly.
6. Classify the result before editing as one primary outcome: `context gap`,
   `deterministic defect`, `supported strength`, `supported skill failure`,
   `case defect`, `World/harness defect`, `judge defect`, or `technical
   inconclusive`. Treat an automatic verdict as evidence to review, not as the
   conclusion.
7. For a supported skill failure, make the smallest change at the decision
   point that would prevent the observed behavior. Preserve unrelated existing
   behavior and wording: edit only the local instruction responsible, and never
   replace a whole paragraph or skill when a narrower edit works. Keep the final
   case and its hash unchanged, rerun it, then run nearby strength cases that
   the change could affect. Never weaken a case or edit it solely to obtain a
   pass.
8. Report changed files, case and skill hashes, exact runs, requested and
   served models when available, usage, reviewed classifications, remaining
   gaps, and the next action. Preserve original artifacts. Keep missing usage,
   technical errors, and unrun work explicit; do not generalize a small sample
   to the whole skill.

Read [decision mapping](references/decision-map.md) before choosing a case,
[case design](references/case-design.md) before authoring or changing one, and
[repair and reporting](references/repair-and-report.md) before running, fixing,
or closing the work.
