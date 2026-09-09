"""Tests for protected-artifact integrity manifests."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from sasguard.cli import app
from sasguard.verification.integrity import (
    ProtectedArtifactManifest,
    ProtectedFile,
    build_integrity_manifest,
    verify_protected_artifacts,
)

runner = CliRunner()


def create_protected_tree(project_root: Path) -> Path:
    """Create representative supplied files under a temporary project root."""
    protected_root = project_root / "data" / "Project_1"
    protected_root.mkdir(parents=True)
    (protected_root / "program.sas").write_text("data output; run;\n", encoding="utf-8")
    (protected_root / "gold.csv").write_text("PROVIDER_ID,star\n000001,5\n", encoding="utf-8")
    return protected_root


def test_manifest_and_integrity_check_are_deterministic(tmp_path: Path) -> None:
    create_protected_tree(tmp_path)

    first = build_integrity_manifest(tmp_path, ["data/Project_1"])
    second = build_integrity_manifest(tmp_path, ["data\\Project_1"])
    result = verify_protected_artifacts(tmp_path, first)

    assert first == second
    assert [entry.path for entry in first.files] == [
        "data/Project_1/gold.csv",
        "data/Project_1/program.sas",
    ]
    assert result.passed
    assert result.expected_files == 2
    assert result.checked_files == 2


def test_integrity_check_reports_modified_missing_and_unexpected_files(
    tmp_path: Path,
) -> None:
    protected_root = create_protected_tree(tmp_path)
    manifest = build_integrity_manifest(tmp_path, ["data/Project_1"])

    (protected_root / "gold.csv").write_text("changed\n", encoding="utf-8")
    (protected_root / "program.sas").unlink()
    (protected_root / "untracked.txt").write_text("unexpected\n", encoding="utf-8")
    result = verify_protected_artifacts(tmp_path, manifest)

    assert not result.passed
    assert result.modified_files == ["data/Project_1/gold.csv"]
    assert result.missing_files == ["data/Project_1/program.sas"]
    assert result.unexpected_files == ["data/Project_1/untracked.txt"]


def test_manifest_rejects_files_outside_protected_roots() -> None:
    entry = ProtectedFile(path="elsewhere/file.csv", sha256="0" * 64)

    with pytest.raises(ValidationError, match="outside protected roots"):
        ProtectedArtifactManifest(
            protected_roots=["data/Project_1"],
            files=[entry],
        )


def test_cli_verifies_manifest_relative_to_project_root(tmp_path: Path) -> None:
    create_protected_tree(tmp_path)
    manifest = build_integrity_manifest(tmp_path, ["data/Project_1"])
    manifest_path = tmp_path / "configs" / "protected-artifacts.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["verify-integrity", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "2 protected files verified" in result.stdout


def test_cli_fails_when_a_protected_file_changes(tmp_path: Path) -> None:
    protected_root = create_protected_tree(tmp_path)
    manifest = build_integrity_manifest(tmp_path, ["data/Project_1"])
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    (protected_root / "gold.csv").write_text("changed\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "verify-integrity",
            "--project-root",
            str(tmp_path),
            "--manifest",
            str(manifest_path),
        ],
    )

    assert result.exit_code == 1
    assert "Modified: data/Project_1/gold.csv" in result.output
