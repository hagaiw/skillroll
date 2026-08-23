"""Render the fixed, deterministic shell around agent-selected PR facts."""

from __future__ import annotations

import argparse


def render(summary: str, validation: str, questions: str) -> str:
    """Render three nonempty text fields in the documented stable order."""
    values = (summary, validation, questions)
    if any(not value.strip() for value in values):
        raise ValueError("summary, validation, and questions must all be nonempty")
    return (
        "# Pull request overview\n\n"
        f"## Summary\n\n{summary.strip()}\n\n"
        f"## Validation\n\n{validation.strip()}\n\n"
        f"## Open questions\n\n{questions.strip()}\n"
    )


def main(arguments: list[str] | None = None) -> int:
    """Provide a tiny no-network self-check for the declared repository check."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    namespace = parser.parse_args(arguments)
    if not namespace.self_test:
        parser.error("only --self-test is supported")
    expected = (
        "# Pull request overview\n\n## Summary\n\nA\n\n"
        "## Validation\n\nB\n\n## Open questions\n\nC\n"
    )
    return 0 if render(" A ", "B", "C") == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
