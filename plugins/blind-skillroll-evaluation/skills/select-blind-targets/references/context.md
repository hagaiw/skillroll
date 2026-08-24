# Selection context

A blind target is selected before its SkillRoll outcome is known. Discovery may
use repository metadata and the active skill tree, but not old run reports,
leaderboards, issue discussions about eval results, or unpublished conclusions.
Do not inspect or copy filenames whose names reveal a prior verdict. When the
user supplies a preregistered ordering rule, apply it without substituting a
result-informed ranking.

## Prefer useful small-repository evidence

- Favor roughly one to ten active skills when comparable candidates exist.
- Count skills only below the repository's intended skills root; fixtures and
  vendored examples are not active skills.
- Seek variation in task shape, repository layout, age, and skill complexity.
- Do not choose a famous repository merely because it is easy to recognize.
- Reject a candidate whose license or access terms do not permit the proposed
  temporary clone and local changes.

## Preregister the target

Record one readable entry per candidate:

```markdown
- Repository: <canonical URL>
  Revision: <full immutable commit SHA>
  Skills root: <relative path>
  Active skills: <count and paths>
  Why selected: <small-team fit and variation>
  Limitations: <freshness, access, or none>
```

Resolve mutable branch names to commits before the trial. If remote freshness
was not checked, say so rather than calling a local revision latest. Keep the
selection artifact free of inference results so it can be handed to a fresh
preparation or authoring worker. Mark an unavailable URL, root, path, license,
or revision as a limitation rather than guessing it.
