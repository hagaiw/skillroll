#!/usr/bin/env python3
"""Initialize and structurally validate a session-scoped FACTS.md file."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import tempfile
from pathlib import Path

HEADER = "# Fact book"
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
RECORD_HEADING = re.compile(r"^### (?P<identifier>R-[0-9]{3,}) — (?P<title>.+)$")
RECORD_ID = re.compile(r"^R-[0-9]{3,}$")
ALLOWED_STATUSES = {"active", "stale", "disputed", "superseded"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
REQUIRED_FIELDS = {
    "Status",
    "Confidence",
    "Created",
    "Updated",
    "Last verified",
    "Source",
    "Context",
    "Statement",
}
RECORD_FIELDS = REQUIRED_FIELDS | {"Tags", "Review by", "Supersedes", "Note"}
SESSION_FIELDS = {"Scope", "Started", "Last updated", "Review rule"}


def _parse_date(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _is_date(value: str) -> bool:
    """Accept only the compact ISO date used by the Markdown format."""
    return DATE_PATTERN.fullmatch(value) is not None and _parse_date(value) is not None


def _field(line: str) -> tuple[str, str] | None:
    if not line.startswith("- ") or ": " not in line[2:]:
        return None
    label, value = line[2:].split(": ", 1)
    return label, value.strip()


def _parse_field_block(
    lines: list[str], *, allowed: set[str], location: str
) -> tuple[dict[str, str], list[str]]:
    fields: dict[str, str] = {}
    errors: list[str] = []
    in_comment = False
    for offset, line in enumerate(lines, start=1):
        if "<!--" in line:
            in_comment = True
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if not line.strip():
            continue
        parsed = _field(line)
        if parsed is None:
            errors.append(f"{location}:{offset}: expected a '- Field: value' line.")
            continue
        label, value = parsed
        if label not in allowed:
            errors.append(f"{location}:{offset}: unknown field '{label}'.")
        elif label != "Source" and label in fields:
            errors.append(f"{location}:{offset}: field '{label}' is repeated.")
        elif label == "Source":
            previous = fields.get(label)
            fields[label] = value if previous is None else f"{previous}\n{value}"
        else:
            fields[label] = value
    return fields, errors


def _validate_record(
    identifier: str, title: str, fields: dict[str, str], location: str
) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - fields.keys())
    if missing:
        errors.append(
            f"{location}: record {identifier} is missing {', '.join(missing)}."
        )
    if not title.strip():
        errors.append(f"{location}: record {identifier} needs a title.")
    status = fields.get("Status")
    if status is not None and status not in ALLOWED_STATUSES:
        errors.append(f"{location}: record {identifier} has an invalid Status.")
    confidence = fields.get("Confidence")
    if confidence is not None and confidence not in ALLOWED_CONFIDENCE:
        errors.append(f"{location}: record {identifier} has an invalid Confidence.")
    for name in ("Created", "Updated", "Last verified"):
        value = fields.get(name)
        if value is not None and not _is_date(value):
            errors.append(
                f"{location}: record {identifier} has an invalid {name} date."
            )
    review_by = fields.get("Review by")
    if review_by is not None and review_by != "not set" and not _is_date(review_by):
        errors.append(f"{location}: record {identifier} has an invalid Review by date.")
    source_values = fields.get("Source", "").splitlines()
    if not source_values or any(
        not value.strip() or value.casefold().startswith("none")
        for value in source_values
    ):
        errors.append(f"{location}: fact {identifier} needs a concrete Source.")
    for name in ("Context", "Statement"):
        if not fields.get(name, "").strip():
            errors.append(f"{location}: record {identifier} needs a non-empty {name}.")
    created = _parse_date(fields.get("Created", ""))
    updated = _parse_date(fields.get("Updated", ""))
    verified = _parse_date(fields.get("Last verified", ""))
    if created is not None and updated is not None and created > updated:
        errors.append(
            f"{location}: record {identifier} Created cannot be after Updated."
        )
    if created is not None and verified is not None and created > verified:
        errors.append(
            f"{location}: record {identifier} Created cannot be after Last verified."
        )
    return errors


def validate_text(text: str) -> list[str]:
    """Return structural and lifecycle errors without making network calls."""
    lines = text.splitlines()
    errors: list[str] = []
    if not lines or lines[0].strip() != HEADER:
        errors.append("line 1: file must start with '# Fact book'.")
        return errors
    try:
        session_start = lines.index("## Session")
    except ValueError:
        errors.append("file needs a '## Session' section.")
        session_start = -1
    try:
        records_start = lines.index("## Records")
    except ValueError:
        errors.append("file needs a '## Records' section.")
        records_start = -1
    if session_start >= 0 and records_start >= 0 and session_start >= records_start:
        errors.append("'## Session' must appear before '## Records'.")
    if session_start >= 0 and records_start > session_start:
        session_fields, session_errors = _parse_field_block(
            lines[session_start + 1 : records_start],
            allowed=SESSION_FIELDS,
            location="session",
        )
        errors.extend(session_errors)
        for name in ("Scope", "Started", "Last updated"):
            if not session_fields.get(name, "").strip():
                errors.append(f"session: missing {name}.")
        for name in ("Started", "Last updated"):
            value = session_fields.get(name)
            if value is not None and not _is_date(value):
                errors.append(f"session: invalid {name} date.")
        started = _parse_date(session_fields.get("Started", ""))
        last_updated = _parse_date(session_fields.get("Last updated", ""))
        if started is not None and last_updated is not None and started > last_updated:
            errors.append("session: Started cannot be after Last updated.")
    if records_start < 0:
        return errors
    record_lines = lines[records_start + 1 :]
    headings: list[tuple[int, re.Match[str]]] = []
    active_heading = False
    in_comment = False
    for index, line in enumerate(record_lines, start=records_start + 1):
        if "<!--" in line:
            in_comment = True
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if not line.startswith("### "):
            if line.strip() and not active_heading:
                errors.append(
                    f"line {index + 1}: record content must appear under a valid "
                    "R-### heading."
                )
            continue
        match = RECORD_HEADING.fullmatch(line)
        if match is None:
            errors.append(f"line {index + 1}: record heading must use an R-### ID.")
            active_heading = False
        else:
            headings.append((index, match))
            active_heading = True
    identifiers: set[str] = set()
    records: dict[str, dict[str, str]] = {}
    for ordinal, (heading_index, match) in enumerate(headings):
        identifier = match.group("identifier")
        title = match.group("title").strip()
        if identifier in identifiers:
            errors.append(
                f"line {heading_index + 1}: record ID {identifier} is repeated."
            )
        identifiers.add(identifier)
        end = headings[ordinal + 1][0] if ordinal + 1 < len(headings) else len(lines)
        block = lines[heading_index + 1 : end]
        fields, field_errors = _parse_field_block(
            block, allowed=RECORD_FIELDS, location=f"record {identifier}"
        )
        errors.extend(field_errors)
        errors.extend(
            _validate_record(identifier, title, fields, f"record {identifier}")
        )
        records[identifier] = fields
    for identifier, fields in records.items():
        target = fields.get("Supersedes")
        if target is None:
            continue
        if not RECORD_ID.fullmatch(target):
            errors.append(
                f"record {identifier}: Supersedes must name an R-### record ID."
            )
        elif target == identifier:
            errors.append(f"record {identifier}: Supersedes cannot refer to itself.")
        elif target not in records:
            errors.append(
                f"record {identifier}: Supersedes target {target} is missing."
            )
        else:
            current_updated = _parse_date(fields.get("Updated", ""))
            target_updated = _parse_date(records[target].get("Updated", ""))
            if (
                current_updated is not None
                and target_updated is not None
                and current_updated < target_updated
            ):
                errors.append(
                    f"record {identifier}: Supersedes target {target} is newer "
                    "than the replacing record."
                )
    return errors


def _template_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "FACTS.md.template"


def _render_template(scope: str, date: str) -> str:
    template = _template_path().read_text(encoding="utf-8")
    return template.replace("{{SCOPE}}", scope).replace("{{DATE}}", date)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as opened:
            temporary = Path(opened.name)
            opened.write(text)
            opened.flush()
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _sample_book() -> str:
    return """# Fact book

## Session

- Scope: Test fact-book validation
- Started: 2026-08-18
- Last updated: 2026-08-18
- Review rule: Re-check time-sensitive records.

## Records

### R-001 — Stable fact

- Status: active
- Confidence: high
- Created: 2026-08-18
- Updated: 2026-08-18
- Last verified: 2026-08-18
- Tags: test
- Source: file: example.py#L1 — value = 1
- Context: The test scope.
- Statement: The value is 1.
"""


def _self_test() -> int:
    valid = _sample_book()
    if validate_text(valid):
        raise ValueError("valid sample was rejected")
    invalid = valid.replace("- Source: file:", "- Source: none — missing")
    if not validate_text(invalid):
        raise ValueError("missing fact source was accepted")
    malformed_books = (
        valid.replace("- Source: file: example.py#L1 — value = 1", "- Source: "),
        valid.replace(
            "### R-001 — Stable fact",
            "- Statement: outside a record\n\n### R-001 — Stable fact",
        ),
        valid.replace(
            "- Statement: The value is 1.",
            "- Supersedes: R-999\n- Statement: The value is 1.",
        ),
        valid.replace(
            "- Statement: The value is 1.",
            "- Supersedes: R-001\n- Statement: The value is 1.",
        ),
        valid.replace("- Created: 2026-08-18", "- Created: 2026-08-19", 1),
    )
    if any(not validate_text(book) for book in malformed_books):
        raise ValueError("malformed fact-book content was accepted")
    print("PASS: fact_book.py self-test")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize or validate a session-scoped FACTS.md file."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="create a new fact-book")
    init.add_argument("path", type=Path)
    init.add_argument("--scope", required=True, help="one-task scope for the book")
    init.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="ISO date to use for session metadata (defaults to today)",
    )
    init.add_argument("--force", action="store_true", help="replace an existing file")
    check = subparsers.add_parser("check", help="validate an existing fact-book")
    check.add_argument("path", type=Path)
    subparsers.add_parser("self-test", help="run the script's deterministic self-test")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "self-test":
        try:
            return _self_test()
        except ValueError as error:
            print(f"FAIL: {error}", file=sys.stderr)
            return 1
    if args.command == "init":
        if not args.scope.strip() or "\n" in args.scope or "\r" in args.scope:
            print("ERROR: --scope must be a non-empty single line.", file=sys.stderr)
            return 2
        if not _is_date(args.date):
            print("ERROR: --date must be an ISO date (YYYY-MM-DD).", file=sys.stderr)
            return 2
        if args.path.exists() and not args.force:
            print(
                f"ERROR: {args.path} already exists; omit --force to preserve it.",
                file=sys.stderr,
            )
            return 2
        try:
            _write_atomic(args.path, _render_template(args.scope.strip(), args.date))
        except OSError as error:
            print(f"ERROR: could not initialize {args.path}: {error}", file=sys.stderr)
            return 1
        print(f"Initialized {args.path} for scope: {args.scope.strip()}")
        return 0
    try:
        text = args.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"ERROR: could not read {args.path}: {error}", file=sys.stderr)
        return 1
    errors = validate_text(text)
    if errors:
        print(f"FAIL: {args.path} has {len(errors)} issue(s).", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"PASS: {args.path} is a valid fact-book.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
