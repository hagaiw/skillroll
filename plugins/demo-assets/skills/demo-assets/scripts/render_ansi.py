"""Convert a prepared mascot source into portable Chafa ANSI files."""

import argparse
import shutil
import subprocess
from pathlib import Path


def render(source: Path, destination: Path, *, colors: str) -> None:
    chafa = shutil.which("chafa")
    if chafa is None:
        raise SystemExit("chafa is required to render ANSI assets")
    command = [
        chafa,
        "--format",
        "symbols",
        "--colors",
        colors,
        "--symbols",
        "block+half+quad+sextant",
        "--size",
        "48x28",
        "--relative",
        "off",
        "--polite",
        "on",
        "--color-extractor",
        "median",
        "--work",
        "9",
    ]
    if colors == "full":
        command.extend(("--preprocess", "off", "--dither", "none"))
    else:
        command.extend(
            (
                "--preprocess",
                "on",
                "--dither",
                "ordered",
                "--dither-intensity",
                "0.35",
                "--color-space",
                "din99d",
            )
        )
    completed = subprocess.run(command + [str(source)], check=True, capture_output=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(completed.stdout)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--colors", choices=("full", "256"), default="full")
    arguments = parser.parse_args()
    render(arguments.source, arguments.destination, colors=arguments.colors)


if __name__ == "__main__":
    main()
