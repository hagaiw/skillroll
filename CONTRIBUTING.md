# Contributing to SkillRoll

SkillRoll is a small, single-maintainer project. Keep changes focused and easy
to review.

## Before coding

- Search existing issues and pull requests.
- Open an issue before a feature, provider, architecture, or public-behavior
  change. Small documentation fixes, tests, and eval examples may go directly
  to a pull request.
- Disclose any need for credentials, paid inference, network access, or
  repository command execution before using it.

## Make one complete change

A bug fix needs a regression test that fails without the fix. New behavior
needs focused tests and updates to affected CLI help, generated content,
examples, and guides.

In the pull request, explain the problem and solution, compatibility or
security effects, checks run, and any remaining limitations. Never commit keys,
private prompts, provider headers, private repository content, or unreviewed
evidence.

## Verify

SkillRoll uses Python 3.12 or later and `uv`:

```shell
uv sync --all-groups --locked
uv run pytest -q
uv run coverage run -m pytest
uv run coverage report --show-missing --fail-under=100
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src tools
```

Run focused tests while iterating, then the full checks before requesting
review. The default suite excludes credentialed `live` checks and optional
`external` CLI integrations. Run those explicitly only after reviewing their
prerequisites and cost.

AI assistance is welcome, but the human submitter owns every changed line and
should disclose the tool, review performed, and uncertain generated work.

For vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a
public issue.
