"""Pure renderers for the small files owned by ``skillroll init``."""

from __future__ import annotations

from pathlib import PurePosixPath


def _toml_string(value: str) -> str:
    """Encode a TOML basic string without letting data alter its structure."""
    escaped: list[str] = []
    for character in value:
        escaped.append(
            {
                "\\": "\\\\",
                '"': '\\"',
                "\b": "\\b",
                "\t": "\\t",
                "\n": "\\n",
                "\f": "\\f",
                "\r": "\\r",
            }.get(
                character,
                (
                    f"\\u{ord(character):04x}"
                    if ord(character) < 0x20 or ord(character) == 0x7F
                    else character
                ),
            )
        )
    return '"' + "".join(escaped) + '"'


def render_config(
    skills_path: PurePosixPath,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
) -> bytes:
    """Render an intentionally minimal, hand-editable TOML configuration."""
    lines = [
        "schema_version = 1",
        f"skills_path = {_toml_string(skills_path.as_posix())}",
    ]
    if base_url is not None and model is not None and api_key_env is not None:
        lines.extend(
            [
                "",
                "[inference]",
                f"base_url = {_toml_string(base_url)}",
                f"model = {_toml_string(model)}",
                f"api_key_env = {_toml_string(api_key_env)}",
            ]
        )
    return ("\n".join(lines) + "\n").encode()


def render_ignore(existing: str | None) -> bytes:
    """Add private run and experiment-artifact rules without other changes."""
    rules = (".skillroll/runs/", ".skillroll/experiments/")
    if existing is None:
        return "".join(f"{rule}\n" for rule in rules).encode()
    lines = existing.splitlines()
    missing = [rule for rule in rules if rule not in lines]
    if not missing:
        return existing.encode()
    newline = "\r\n" if "\r\n" in existing else "\n"
    rendered = existing
    for rule in missing:
        suffix = "" if not rendered or rendered.endswith(("\n", "\r")) else newline
        rendered += suffix + rule + newline
    return rendered.encode()


def render_starter_case(name: str) -> bytes:
    """Render one structurally valid but explicitly non-authoritative eval case."""
    return (
        f"# {name.replace('-', ' ').title()}\n\n"
        "```skillroll\n"
        "schema_version: 1\n"
        "```\n\n"
        "## Input\n\n"
        "Write the request or task that triggers the skill.\n\n"
        "## World\n\n"
        "Describe what the Dungeon Master should simulate: facts the skill must "
        "discover, people or systems it may interact with, and likely action "
        "results.\n\n"
        "## Success criteria\n\n"
        "- Describe one observable behavior that must succeed. Allow equivalent "
        "actions and wording.\n"
    ).encode()
