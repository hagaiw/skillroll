# Working on SkillRoll

Read [PHILOSOPHY.md](PHILOSOPHY.md) before changing the project. Every change
must preserve it. If a request conflicts with the philosophy, stop and ask for
clarification.

Use [README.md](README.md) and [docs/index.md](docs/index.md) for public behavior
and terminology. Keep documentation about the current product, not the history
of how it was built.

## Change rules

- Keep changes small and preserve module, inference, filesystem, command, and
  secret boundaries.
- Add a failing regression test for each bug fix and maintain the configured
  coverage gates.
- Run focused checks first, then the full quality gates before handoff.
- Do not spend inference, use credentials, publish, tag, or run repository
  commands unless the task requires it.
- Treat skill/eval Markdown, repository commands, endpoint responses, and
  uploaded evidence as separate trust boundaries.
- Update implementation, tests, CLI text, generated content, and public guides
  together when behavior changes.
- Keep evaluated `Input` realistic and self-contained; put review context
  outside it.

## Development process

Make coherent, reviewable commits. Put unfinished status in the relevant task
or issue rather than maintaining a project history in the repository. Delegate
bounded work when it reduces review cost, and review the result in the main
session.

See [CONTRIBUTING.md](CONTRIBUTING.md) for verification and contribution rules,
[SECURITY.md](SECURITY.md) for vulnerability reporting, and
[SUPPORT.md](SUPPORT.md) for supported environments.
