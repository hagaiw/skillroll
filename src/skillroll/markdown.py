"""Markdown token handling for sections, fences, and ordinary links."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

from skillroll.diagnostics import SourceLocation

_MARKDOWN = MarkdownIt("commonmark")


@dataclass(frozen=True, slots=True)
class MetadataFence:
    content: str
    line: int


def tokens(source: str) -> tuple[Token, ...]:
    return tuple(_MARKDOWN.parse(source))


def first_metadata_fence(source: str) -> MetadataFence | None:
    """Return only a correctly positioned first ``skillroll`` fence."""
    parsed = tokens(source)
    meaningful = [
        item for item in parsed if item.type not in {"inline", "heading_close"}
    ]
    index = 0
    if (
        len(meaningful) >= 2
        and meaningful[0].type == "heading_open"
        and meaningful[0].tag == "h1"
    ):
        index = 1
    if index >= len(meaningful) or meaningful[index].type != "fence":
        return None
    fence = meaningful[index]
    if fence.info.strip() != "skillroll":
        return None
    line = (fence.map or [0])[0] + 1
    return MetadataFence(fence.content, line)


def metadata_fence_count(source: str) -> int:
    return sum(
        1
        for item in tokens(source)
        if item.type == "fence" and item.info.strip() == "skillroll"
    )


def sections(source: str) -> dict[str, tuple[str, int]]:
    """Extract exact level-two sections and their Markdown source lines."""
    lines = source.splitlines(keepends=True)
    result: dict[str, tuple[str, int]] = {}
    parsed = tokens(source)
    headings = [
        item
        for item in parsed
        if item.type == "heading_open" and item.tag in {"h1", "h2"}
    ]
    for position, heading in enumerate(headings):
        if heading.tag != "h2" or heading.map is None:
            continue
        start, heading_end = heading.map
        title = "".join(lines[start:heading_end]).lstrip("#").strip()
        end = len(lines)
        for following in headings[position + 1 :]:
            if following.map is not None:
                end = following.map[0]
                break
        content = "".join(lines[heading_end:end]).strip()
        if title in result:
            result[title] = ("", start + 1)
        else:
            result[title] = (content, start + 1)
    return result


def title(source: str) -> str | None:
    parsed = tokens(source)
    for index, item in enumerate(parsed):
        if item.type == "heading_open" and item.tag == "h1" and index + 1 < len(parsed):
            return parsed[index + 1].content.strip() or None
    return None


def local_links(source: str) -> tuple[str, ...]:
    """Return only filesystem-like Markdown destinations."""
    links: list[str] = []
    for token in tokens(source):
        if token.type != "inline" or token.children is None:
            continue
        for child in token.children:
            if child.type != "link_open":
                continue
            destination = child.attrGet("href")
            if not isinstance(destination, str):
                continue
            parsed = urlsplit(destination)
            if (
                parsed.scheme
                or destination.startswith("/")
                or destination.startswith("#")
            ):
                continue
            if not parsed.path:
                continue
            links.append(unquote(parsed.path))
    return tuple(links)


def location(path: str, line: int) -> SourceLocation:
    return SourceLocation(path, line, 1)
