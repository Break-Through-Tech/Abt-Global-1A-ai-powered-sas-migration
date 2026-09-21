"""Integrity manifests and checks for supplied project artifacts."""

from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sasguard.provenance.hashing import (
    normalize_relative_path,
    sha256_file,
    validate_sha256,
)


def _is_within(path: str, root: str) -> bool:
    path_parts = PurePosixPath(path).parts
    root_parts = PurePosixPath(root).parts
    return path_parts[: len(root_parts)] == root_parts


class ProtectedFile(BaseModel):
    """Expected path and digest for one immutable supplied artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    sha256: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return normalize_relative_path(value)

    @field_validator("sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        return validate_sha256(value)


class ProtectedArtifactManifest(BaseModel):
    """Versioned declaration of supplied files that must not change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    algorithm: Literal["sha256"] = "sha256"
    protected_roots: list[str] = Field(min_length=1)
    files: list[ProtectedFile] = Field(min_length=1)

    @field_validator("protected_roots")
    @classmethod
    def validate_roots(cls, values: list[str]) -> list[str]:
        normalized = [normalize_relative_path(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("protected roots must be unique")
        return sorted(normalized)

    @model_validator(mode="after")
    def validate_file_paths(self) -> Self:
        paths = [entry.path for entry in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("protected file paths must be unique")
        outside_roots = [
            path
            for path in paths
            if not any(_is_within(path, root) for root in self.protected_roots)
        ]
        if outside_roots:
            raise ValueError(f"files are outside protected roots: {outside_roots}")
        return self

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load and validate a JSON integrity manifest."""
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class IntegrityCheckResult(BaseModel):
    """Path-only diagnostics from a protected-artifact integrity check."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    expected_files: int = Field(ge=0)
    checked_files: int = Field(ge=0)
    missing_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    unexpected_files: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.checked_files > self.expected_files:
            raise ValueError("checked file count cannot exceed expected file count")
        has_failures = bool(self.missing_files or self.modified_files or self.unexpected_files)
        if self.passed == has_failures:
            raise ValueError("integrity status does not match its diagnostics")
        return self


def build_integrity_manifest(
    project_root: Path, protected_roots: list[str]
) -> ProtectedArtifactManifest:
    """Build a deterministic manifest for explicitly protected directories."""
    root = project_root.resolve()
    normalized_roots = sorted({normalize_relative_path(path) for path in protected_roots})
    entries: list[ProtectedFile] = []

    for relative_root in normalized_roots:
        absolute_root = (root / Path(relative_root)).resolve()
        if not absolute_root.is_relative_to(root):
            raise ValueError(f"protected root escapes project root: {relative_root}")
        if not absolute_root.is_dir():
            raise FileNotFoundError(absolute_root)
        for path in sorted(item for item in absolute_root.rglob("*") if item.is_file()):
            if path.is_symlink():
                raise ValueError(f"protected artifacts must not be symlinks: {path}")
            relative_path = normalize_relative_path(path.relative_to(root).as_posix())
            entries.append(ProtectedFile(path=relative_path, sha256=sha256_file(path)))

    return ProtectedArtifactManifest(
        protected_roots=normalized_roots,
        files=sorted(entries, key=lambda entry: entry.path),
    )


def verify_protected_artifacts(
    project_root: Path, manifest: ProtectedArtifactManifest
) -> IntegrityCheckResult:
    """Compare protected files on disk with a trusted integrity manifest."""
    root = project_root.resolve()
    expected = {entry.path: entry.sha256 for entry in manifest.files}
    actual_paths: set[str] = set()

    for relative_root in manifest.protected_roots:
        absolute_root = (root / Path(relative_root)).resolve()
        if not absolute_root.is_relative_to(root):
            raise ValueError(f"protected root escapes project root: {relative_root}")
        if not absolute_root.exists():
            continue
        if not absolute_root.is_dir():
            raise ValueError(f"protected root is not a directory: {relative_root}")
        for path in (item for item in absolute_root.rglob("*") if item.is_file()):
            if path.is_symlink():
                raise ValueError(f"protected artifacts must not be symlinks: {path}")
            actual_paths.add(normalize_relative_path(path.relative_to(root).as_posix()))

    expected_paths = set(expected)
    missing = sorted(expected_paths - actual_paths)
    unexpected = sorted(actual_paths - expected_paths)
    modified = sorted(
        path
        for path in expected_paths & actual_paths
        if sha256_file(root / Path(path)) != expected[path]
    )
    checked_files = len(expected_paths & actual_paths)

    return IntegrityCheckResult(
        passed=not (missing or modified or unexpected),
        expected_files=len(expected_paths),
        checked_files=checked_files,
        missing_files=missing,
        modified_files=modified,
        unexpected_files=unexpected,
    )


def load_and_verify_integrity(project_root: Path, manifest_path: Path) -> IntegrityCheckResult:
    """Load a manifest and verify its protected files."""
    return verify_protected_artifacts(project_root, ProtectedArtifactManifest.load(manifest_path))
