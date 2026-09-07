"""Normalize Markdown ATX heading spacing without changing note content."""

from __future__ import annotations

import re
import sys

_ATX_HEADING = re.compile(r"^( {0,3})(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,}).*$")
_RAW_TAG_OPEN = re.compile(r"<(script|pre|style|textarea)(?:[ \t>]|$)", re.IGNORECASE)


def _line_parts(raw_line: str) -> tuple[str, str]:
    """Return a line's content and its original line ending."""
    for ending in ("\r\n", "\n", "\r"):
        if raw_line.endswith(ending):
            return raw_line[: -len(ending)], ending
    return raw_line, ""


def _closes_fence(line: str, marker: str, minimum: int) -> bool:
    """Return whether line closes the active CommonMark fenced code block."""
    candidate = line.lstrip(" ")
    indentation = len(line) - len(candidate)
    if indentation > 3:
        return False
    run_length = len(candidate) - len(candidate.lstrip(marker))
    return run_length >= minimum and not candidate[run_length:].strip(" \t")


def _raw_html_end(line: str) -> str | None:
    """Return the terminator for a raw HTML region starting on line."""
    candidate = line.lstrip(" ")
    if len(line) - len(candidate) > 3:
        return None
    tag = _RAW_TAG_OPEN.match(candidate)
    if tag is not None:
        return f"</{tag.group(1).lower()}>"
    if candidate.startswith("<!--"):
        return "-->"
    if candidate.startswith("<?"):
        return "?>"
    if candidate.startswith("<![CDATA["):
        return "]]>"
    if re.match(r"<![A-Z]", candidate):
        return ">"
    if candidate.startswith("<"):
        return ""
    return None


def normalize_headings(text: str) -> str:
    """Normalize Markdown ATX headings without adding or removing content."""
    if not text:
        return ""

    normalized: list[str] = []
    active_fence: tuple[str, int] | None = None
    raw_html_end: str | None = None
    for raw_line in text.splitlines(keepends=True):
        line, ending = _line_parts(raw_line)

        if raw_html_end is not None:
            normalized.append(raw_line)
            if (raw_html_end and raw_html_end in line.lower()) or (
                not raw_html_end and not line.strip()
            ):
                raw_html_end = None
            continue

        if active_fence is not None:
            normalized.append(raw_line)
            marker, minimum = active_fence
            if _closes_fence(line, marker, minimum):
                active_fence = None
            continue

        fence = _FENCE_OPEN.fullmatch(line)
        if fence is not None:
            delimiter = fence.group(1)
            active_fence = (delimiter[0], len(delimiter))
            normalized.append(raw_line)
            continue

        raw_end = _raw_html_end(line)
        if raw_end is not None:
            normalized.append(raw_line)
            if (raw_end and raw_end not in line.lower()) or (
                not raw_end and line.strip()
            ):
                raw_html_end = raw_end
            continue

        match = _ATX_HEADING.fullmatch(line)
        if match is None:
            normalized.append(raw_line)
            continue

        indentation = match.group(1)
        marks = match.group(2)
        title = (match.group(3) or "").strip()
        normalized.append(f"{indentation}{marks} {title}{ending}")

    return "".join(normalized)


def main() -> int:
    """Read UTF-8 stdin and write the normalized UTF-8 result."""
    source = sys.stdin.buffer.read().decode("utf-8")
    sys.stdout.buffer.write(normalize_headings(source).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
