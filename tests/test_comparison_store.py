"""Safety contract for private comparison evidence storage."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import pytest

from skillroll.artifacts import store as store_module
from skillroll.artifacts.store import ArtifactError, ArtifactStore
from skillroll.inference.profile import SecretRedactor, SecretValue

SECRET = "comparison-token/one"


def new_store(root: Path, id_factory=lambda: "fixed") -> ArtifactStore:
    return ArtifactStore(root, SecretRedactor(SecretValue(SECRET)), id_factory)


def test_create_comparison_is_private_and_retries_collisions(tmp_path: Path) -> None:
    first = new_store(tmp_path)
    first_id, first_directory = first.create_comparison()
    assert first_id == "comparison-fixed"
    assert first_directory == tmp_path / ".skillroll" / "comparisons" / first_id

    identifiers = iter(("fixed", "next"))
    second = new_store(tmp_path, lambda: next(identifiers))
    comparison_id, directory = second.create_comparison()
    assert comparison_id == "comparison-next"
    assert directory.is_dir()
    if os.name == "posix":
        assert directory.stat().st_mode & 0o077 == 0

    with pytest.raises(ArtifactError, match="unique"):
        first.create_comparison()


def test_create_comparison_rejects_unsafe_layouts(tmp_path: Path) -> None:
    unsafe_root = tmp_path / "not-a-directory"
    unsafe_root.write_text("file", encoding="utf-8")
    with pytest.raises(ArtifactError, match="repository folder is unsafe"):
        new_store(unsafe_root).create_comparison()

    base_file = tmp_path / "base-file"
    base_file.mkdir()
    (base_file / ".skillroll").write_text("file", encoding="utf-8")
    with pytest.raises(ArtifactError, match=".skillroll is not an ordinary folder"):
        new_store(base_file).create_comparison()

    comparisons_file = tmp_path / "comparisons-file"
    (comparisons_file / ".skillroll").mkdir(parents=True)
    (comparisons_file / ".skillroll" / "comparisons").write_text(
        "file", encoding="utf-8"
    )
    with pytest.raises(
        ArtifactError, match=".skillroll/comparisons is not an ordinary folder"
    ):
        new_store(comparisons_file).create_comparison()

    for path_name in ("base-link", "comparisons-link"):
        repository = tmp_path / path_name
        repository.mkdir()
        target = tmp_path / f"{path_name}-target"
        target.mkdir()
        if path_name == "base-link":
            (repository / ".skillroll").symlink_to(target, target_is_directory=True)
        else:
            (repository / ".skillroll").mkdir()
            (repository / ".skillroll" / "comparisons").symlink_to(
                target, target_is_directory=True
            )
        with pytest.raises(ArtifactError, match="not an ordinary folder"):
            new_store(repository).create_comparison()


def test_create_comparison_wraps_directory_creation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_mkdir = Path.mkdir

    def broken_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        if path.name == "comparisons":
            raise OSError("disk unavailable")
        original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", broken_mkdir)
    with pytest.raises(ArtifactError, match="could not create"):
        new_store(tmp_path).create_comparison()


@pytest.mark.parametrize("descriptor_safety", [True, False])
def test_write_comparison_redacts_and_writes_only_allowed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    descriptor_safety: bool,
) -> None:
    if descriptor_safety and not store_module._descriptor_safety_available():
        pytest.skip("Descriptor-relative filesystem writes are unavailable")
    monkeypatch.setattr(
        store_module, "_descriptor_safety_available", lambda: descriptor_safety
    )
    store = new_store(tmp_path)
    comparison_id, directory = store.create_comparison()
    names = ("manifest.json", "comparison.json", "report.md")
    values = tuple(
        (
            name,
            f"{name}: {SECRET}; encoded: {quote(SECRET, safe='')}".encode(),
        )
        for name in names
    )

    store.write_comparison(directory, values)

    assert comparison_id == directory.name
    assert {path.name for path in directory.iterdir()} == set(names)
    for name, _ in values:
        contents = (directory / name).read_bytes()
        assert SECRET.encode() not in contents
        assert quote(SECRET, safe="").encode() not in contents
        assert b"[redacted]" in contents


@pytest.mark.parametrize("descriptor_safety", [True, False])
def test_write_comparison_rejects_outside_missing_and_symlink_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    descriptor_safety: bool,
) -> None:
    if descriptor_safety and not store_module._descriptor_safety_available():
        pytest.skip("Descriptor-relative filesystem writes are unavailable")
    monkeypatch.setattr(
        store_module, "_descriptor_safety_available", lambda: descriptor_safety
    )
    store = new_store(tmp_path)
    _, directory = store.create_comparison()
    values = (("report.md", b"report"),)

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ArtifactError, match="outside"):
        store.write_comparison(outside, values)
    missing = directory.with_name("comparison-missing")
    with pytest.raises(ArtifactError, match="safely reopen"):
        store.write_comparison(missing, values)

    moved = directory.with_name("moved")
    directory.rename(moved)
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactError, match="folder|link"):
        store.write_comparison(directory, values)
    assert not list(outside.iterdir())


def test_write_comparison_rejects_unapproved_file_names(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    _, directory = store.create_comparison()
    for unsafe_name in ("../escaped", "report.md/../escaped", "inputs.json"):
        with pytest.raises(ArtifactError, match="unsafe comparison file name"):
            store.write_comparison(directory, ((unsafe_name, b"data"),))
    assert not list(directory.iterdir())
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("descriptor_safety", [True, False])
def test_write_comparison_wraps_atomic_write_errors_and_cleans_temporary_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    descriptor_safety: bool,
) -> None:
    if descriptor_safety and not store_module._descriptor_safety_available():
        pytest.skip("Descriptor-relative filesystem writes are unavailable")
    monkeypatch.setattr(
        store_module, "_descriptor_safety_available", lambda: descriptor_safety
    )
    store = new_store(tmp_path)
    _, directory = store.create_comparison()

    def failed_replace(*args: object, **kwargs: object) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(os, "replace", failed_replace)
    with pytest.raises(ArtifactError, match="could not atomically write manifest.json"):
        store.write_comparison(directory, (("manifest.json", b"{}"),))
    assert not list(directory.glob(".*.tmp"))
