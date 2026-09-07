"""Normalize Markdown ATX heading spacing without changing note content."""

from __future__ import annotations

import re
import sys

_ATX_HEADING = re.compile(r"^[ \t]*(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_MARKERS = re.compile(r"[ \t]+(?:#+[ \t]*)+$")


def normalize_headings(text: str) -> str:
    """Normalize Markdown ATX headings without adding or removing content."""
    if not text:
        return ""

    had_trailing_newline = text.endswith(("\n", "\r"))
    lines = text.splitlines()
    normalized: list[str] = []
    for line in lines:
        match = _ATX_HEADING.fullmatch(line)
        if match is None:
            normalized.append(line)
            continue

        marks = match.group(1)
        title = (match.group(2) or "").strip()
        title = _CLOSING_MARKERS.sub("", title).rstrip()
        if title and set(title) == {"#"}:
            title = ""
        normalized.append(f"{marks} {title}")

    result = "\n".join(normalized)
    return result + ("\n" if had_trailing_newline else "")


def main() -> int:
    """Read UTF-8 stdin and write the normalized UTF-8 result."""
    source = sys.stdin.buffer.read().decode("utf-8")
    sys.stdout.buffer.write(normalize_headings(source).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
