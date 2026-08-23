from __future__ import annotations

import shlex
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_external_checks_require_explicit_opt_in() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_options = project["tool"]["pytest"]["ini_options"]

    options = shlex.split(pytest_options["addopts"])
    marker_expression = options[options.index("-m") + 1]
    assert "not live" in marker_expression
    assert "not external" in marker_expression
    markers = {value.partition(":")[0] for value in pytest_options["markers"]}
    assert {"live", "external"} <= markers


def test_ci_is_read_only_and_secretless() -> None:
    source = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(source)

    permissions = [workflow["permissions"]]
    permissions.extend(
        job["permissions"] for job in workflow["jobs"].values() if "permissions" in job
    )
    assert workflow["permissions"].get("contents") == "read"
    assert all(set(values.values()) <= {"read", "none"} for values in permissions)
    assert "pull_request_target" not in source
    assert "secrets." not in source
