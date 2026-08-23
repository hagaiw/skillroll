"""Release workflow security contract; this test never invokes GitHub."""

from __future__ import annotations

import re

from conftest import ROOT


def test_release_workflow_is_pinned_secretless_and_fail_closed() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    pins = re.findall(r"uses: [^@\s]+@([0-9a-f]{40})", workflow)

    assert "release:\n    types: [published]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request" not in workflow
    assert "pull_request_target" not in workflow
    assert "push:" not in workflow
    assert "secrets." not in workflow
    assert "PYPI_TOKEN" not in workflow
    assert len(pins) == 8
    assert "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6" in workflow
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d" in workflow
    assert (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    )
    assert (
        "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33"
        in workflow
    )
    assert "id-token: write" in workflow
    assert "attestations: write" in workflow
    assert "environment: pypi" in workflow
    assert "needs: [build, attest]" in workflow
    assert "needs.build.outputs.publishable == 'true'" in workflow
    assert "Release rehearsal is BLOCKED; nothing was published." in workflow
    assert "Verify the published tag matches the canonical version" in workflow
    assert "release_metadata().tag" in workflow
    assert "Verify wheel metadata before privileged handoff" in workflow
    assert "Verify generated checksum manifest before handoff" in workflow


def test_release_workflow_keeps_credentials_and_inference_outside_build() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    build = workflow.split("  attest:", maxsplit=1)[0]
    attest = workflow.split("  attest:", maxsplit=1)[1].split(
        "  publish-pypi:", maxsplit=1
    )[0]
    publish = workflow.split("  publish-pypi:", maxsplit=1)[1]

    assert "id-token: write" not in build
    assert "attestations: write" not in build
    assert "SKILLROLL_API_KEY" not in workflow
    assert "INFERENCE" not in workflow
    assert "id-token: write" in attest
    assert "attestations: write" in attest
    assert "id-token: write" in publish
    assert "attestations: write" not in publish
    assert "run:" not in attest
    assert "run:" not in publish
    assert re.findall(r"uses: ([^\s]+)", attest) == [
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6",
    ]
    assert re.findall(r"uses: ([^\s]+)", publish) == [
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
    ]
