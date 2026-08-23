"""Create local unsigned release evidence without publishing or invoking inference."""

from __future__ import annotations

import argparse
from pathlib import Path

from skillroll.release import load_external_gates, write_rehearsal_evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Write evidence and report current external evidence as publication-blocking."""
    values = _parser().parse_args(arguments)
    artifacts = tuple(
        sorted((*values.artifacts.glob("*.whl"), *values.artifacts.glob("*.tar.gz")))
    )
    report = write_rehearsal_evidence(
        root=values.root,
        artifacts=artifacts,
        output=values.output,
        commit=values.commit,
        gates=load_external_gates(values.root / "release-gates.toml"),
    )
    print(report.render(), end="")
    return 0 if report.publishable else 2


if __name__ == "__main__":
    raise SystemExit(main())
