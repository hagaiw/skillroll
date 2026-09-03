# Working on SkillRoll

Read [PRINCIPLES.md](PRINCIPLES.md) before changing the project and preserve
its principles. If a request conflicts with them, stop and ask for
clarification.

Use [README.md](README.md) and [docs/index.md](docs/index.md) for public
terminology and current product behavior.

- Preserve module, inference, filesystem, command, and secret boundaries.
- Treat skill and eval Markdown, repository commands, endpoint responses, and
  uploaded evidence as separate trust boundaries.
- Keep evaluated `Input` realistic and self-contained; put review context
  outside it.

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for contribution and
verification requirements, [SECURITY.md](.github/SECURITY.md) for security
requirements, and [SUPPORT.md](.github/SUPPORT.md) for supported environments
and support requirements.
