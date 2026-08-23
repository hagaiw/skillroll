from __future__ import annotations

import importlib.util

import pytest
from conftest import ROOT


def _module() -> object:
    path = ROOT / "plugins/pr-overview/skills/pr-overview/scripts/render_overview.py"
    spec = importlib.util.spec_from_file_location("pr_overview_renderer", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_renderer_orders_and_trims_the_fixed_sections() -> None:
    module = _module()
    assert module.render(" Summary ", "tests pass", "none") == (
        "# Pull request overview\n\n## Summary\n\nSummary\n\n"
        "## Validation\n\ntests pass\n\n## Open questions\n\nnone\n"
    )
    assert module.main(["--self-test"]) == 0


def test_renderer_rejects_missing_fields() -> None:
    module = _module()
    with pytest.raises(ValueError, match="questions"):
        module.render("summary", "validation", " ")
