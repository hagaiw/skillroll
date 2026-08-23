"""Public release-document contracts."""

from __future__ import annotations

from conftest import ROOT


def test_release_documents_state_real_boundaries() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    support = (ROOT / ".github" / "SUPPORT.md").read_text(encoding="utf-8")
    security = (ROOT / "docs/security.md").read_text(encoding="utf-8")

    assert all(
        value in changelog
        for value in ("[Unreleased]", "[0.1.2]", "[0.1.1]", "[0.1.0]")
    )
    assert all(value in support for value in ("Python 3.12", "Linux", "GitHub"))
    assert all(
        value in security
        for value in ("## Boundaries", "Untrusted pull requests", "API key")
    )
