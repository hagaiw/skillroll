from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from tools.check_function_coverage import (
    find_functions,
    main,
    run,
    uncovered_functions,
)


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / "sample.py"
    source.write_text(
        """from typing import TYPE_CHECKING, overload

def covered():
    \"\"\"Doc.\"\"\"
    return 1

async def missed_async():
    return 2

class Example:
    def method(self):
        def nested():
            return 3
        return nested()

@overload
def ignored(value: int) -> int: ...

if TYPE_CHECKING:
    def type_only():
        return 4
""",
        encoding="utf-8",
    )
    return source


def test_finder_handles_function_kinds_and_explicit_exclusions(tmp_path: Path) -> None:
    source = _write_source(tmp_path)
    assert [(item.name, item.line) for item in find_functions(source)] == [
        ("covered", 5),
        ("missed_async", 8),
        ("Example.method", 12),
        ("Example.method.nested", 13),
    ]


def test_uncovered_functions_are_deterministic(tmp_path: Path) -> None:
    source = _write_source(tmp_path)
    report = {"files": {str(source): {"executed_lines": [5, 12, 13]}}}
    assert [
        (item.name, item.line) for item in uncovered_functions(report, [source])
    ] == [("missed_async", 8)]


def test_run_reports_success_missing_and_bad_inputs(
    tmp_path: Path, capsys: object
) -> None:
    source = tmp_path / "small.py"
    source.write_text("def yes():\n    return True\n", encoding="utf-8")
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps({"files": {str(source): {"executed_lines": [2]}}}),
        encoding="utf-8",
    )
    assert run([str(report), str(source)]) == 0
    report.write_text(
        json.dumps({"files": {str(source): {"executed_lines": []}}}),
        encoding="utf-8",
    )
    assert run([str(report), str(source)]) == 1
    report.write_text("not json", encoding="utf-8")
    assert run([str(report), str(source)]) == 2


def test_checker_rejects_missing_records_and_invalid_source_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.py"
    source.write_text("def x():\n    pass\n", encoding="utf-8")
    for payload in ({}, {"files": {str(source): {"executed_lines": "bad"}}}):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(payload), encoding="utf-8")
        assert run([str(report), str(source)]) == 2
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps({"files": {}}), encoding="utf-8")
    assert run([str(valid), str(source)]) == 2
    assert run([str(valid), str(tmp_path / "missing.txt")]) == 2


def test_directory_relative_records_and_regular_if_are_supported(
    tmp_path: Path,
) -> None:
    source = tmp_path / "branch.py"
    source.write_text(
        "if True:\n    def inside():\n        return 1\n", encoding="utf-8"
    )
    report = {"files": {source.as_posix(): {"executed_lines": [3]}}}
    assert uncovered_functions(report, [tmp_path]) == []


def test_type_checking_else_branch_is_visited(tmp_path: Path) -> None:
    source = tmp_path / "typed.py"
    source.write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    def hidden():\n"
        "        return 1\n"
        "else:\n"
        "    def runtime():\n"
        "        return 2\n",
        encoding="utf-8",
    )
    assert [(item.name, item.line) for item in find_functions(source)] == [
        ("runtime", 7)
    ]


def test_protocol_ellipsis_is_not_a_concrete_function(tmp_path: Path) -> None:
    source = tmp_path / "protocol.py"
    source.write_text(
        "from typing import Protocol\n"
        "class Interface(Protocol):\n"
        "    def abstract(self) -> None:\n"
        '        """A declaration only."""\n'
        "        ...\n"
        "    def default(self) -> int:\n"
        "        return 1\n"
        "class PlainInterface(Protocol):\n"
        "    def plain(self) -> None: ...\n",
        encoding="utf-8",
    )
    assert [(item.name, item.line) for item in find_functions(source)] == [
        ("Interface.default", 7)
    ]


def test_non_object_report_and_command_entrypoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "report.json"
    report.write_text("[]", encoding="utf-8")
    assert run([str(report), str(tmp_path)]) == 2
    monkeypatch.setattr(
        sys, "argv", ["check_function_coverage", str(report), str(tmp_path)]
    )
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
    with (
        pytest.warns(RuntimeWarning, match="found in sys.modules"),
        pytest.raises(SystemExit),
    ):
        runpy.run_module("tools.check_function_coverage", run_name="__main__")
