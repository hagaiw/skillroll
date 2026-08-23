"""Require the first executable line of every maintained function to run."""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple


class Function(NamedTuple):
    path: Path
    name: str
    line: int


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        (isinstance(item, ast.Name) and item.id == "overload")
        or (isinstance(item, ast.Attribute) and item.attr == "overload")
        for item in node.decorator_list
    )


def _first_body_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    body = node.body
    if body and isinstance(body[0], ast.Expr):
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            body = body[1:]
    return body[0].lineno


def _is_protocol_base(base: ast.expr) -> bool:
    return (isinstance(base, ast.Name) and base.id == "Protocol") or (
        isinstance(base, ast.Attribute) and base.attr == "Protocol"
    )


def _is_protocol_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = node.body
    if body and isinstance(body[0], ast.Expr):
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            body = body[1:]
    return (
        len(body) == 1
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and body[0].value.value is Ellipsis
    )


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.functions: list[Function] = []
        self.names: list[str] = []
        self.type_checking = 0
        self.protocol_depth = 0

    def visit_If(self, node: ast.If) -> None:
        is_type_checking = (
            isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
        )
        if is_type_checking:
            self.type_checking += 1
            for item in node.body:
                self.visit(item)
            self.type_checking -= 1
            for item in node.orelse:
                self.visit(item)
        else:
            self.generic_visit(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified = ".".join((*self.names, node.name))
        line = _first_body_line(node)
        if (
            not self.type_checking
            and not _is_overload(node)
            and not (self.protocol_depth and _is_protocol_stub(node))
        ):
            self.functions.append(Function(self.path, qualified, line))
        self.names.append(node.name)
        self.generic_visit(node)
        self.names.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.append(node.name)
        self.protocol_depth += int(any(_is_protocol_base(base) for base in node.bases))
        self.generic_visit(node)
        self.protocol_depth -= int(any(_is_protocol_base(base) for base in node.bases))
        self.names.pop()


def find_functions(path: Path) -> list[Function]:
    """Return concrete functions in a Python source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _Visitor(path)
    visitor.visit(tree)
    return visitor.functions


def _python_files(paths: Iterable[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        if path.is_dir():
            files.update(path.rglob("*.py"))
        elif path.suffix == ".py":
            files.add(path)
        else:
            raise ValueError(f"source path is not a Python file or directory: {path}")
    return sorted(files)


def _executed(report: Mapping[str, Any], path: Path) -> set[int]:
    files = report.get("files")
    if not isinstance(files, dict):
        raise ValueError("coverage report has no 'files' object")
    candidates = (str(path), path.as_posix(), str(path.resolve()))
    record = next((files[item] for item in candidates if item in files), None)
    if not isinstance(record, dict):
        raise ValueError(f"coverage report has no entry for {path}")
    lines = record.get("executed_lines")
    if not isinstance(lines, list) or not all(isinstance(item, int) for item in lines):
        raise ValueError(f"coverage entry for {path} has invalid executed_lines")
    return set(lines)


def uncovered_functions(
    report: Mapping[str, Any], paths: Sequence[Path]
) -> list[Function]:
    """Return functions whose first executable body line is uncovered."""
    missing: list[Function] = []
    for path in _python_files(paths):
        executed = _executed(report, path)
        missing.extend(
            item for item in find_functions(path) if item.line not in executed
        )
    return missing


def run(arguments: Sequence[str]) -> int:
    """Check a coverage JSON report and print actionable failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("sources", nargs="+", type=Path)
    namespace = parser.parse_args(arguments)
    try:
        raw = json.loads(namespace.report.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("coverage report root must be an object")
        missing = uncovered_functions(raw, namespace.sources)
    except (OSError, ValueError, SyntaxError, json.JSONDecodeError) as error:
        print(f"Function coverage could not be checked: {error}")
        return 2
    if missing:
        print("Functions whose bodies were not executed:")
        for item in missing:
            print(f"- {item.path}:{item.line} ({item.name})")
        return 1
    print("Function coverage: 100%")
    return 0


def main() -> None:
    raise SystemExit(run(__import__("sys").argv[1:]))


if __name__ == "__main__":
    main()
