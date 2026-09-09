"""Validated project configuration for SASGuard pipelines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_IDENTIFIER_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_PROJECT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _normalize_relative_path(value: str) -> str:
    """Normalize a portable repository-relative path and reject traversal."""
    candidate = value.replace("\\", "/").strip()
    path = PurePosixPath(candidate)
    if (
        not candidate
        or path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or (path.parts and path.parts[0].endswith(":"))
    ):
        raise ValueError(f"path must be repository-relative: {value!r}")
    return path.as_posix()


def _validate_filename(value: str, suffix: str) -> str:
    """Validate a single portable filename with the required suffix."""
    filename = _normalize_relative_path(value)
    if len(PurePosixPath(filename).parts) != 1:
        raise ValueError(f"expected a filename without directories: {value!r}")
    if not filename.lower().endswith(suffix):
        raise ValueError(f"filename must end with {suffix}: {value!r}")
    return filename


def _validate_unique_case_insensitive(values: list[str], label: str) -> None:
    canonical = [value.casefold() for value in values]
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{label} must be unique ignoring case")


def _resolve_beneath(project_root: Path, relative_path: str) -> Path:
    """Resolve a configured path and guarantee it stays under the project root."""
    root = project_root.resolve()
    portable_path = PurePosixPath(relative_path)
    resolved = (root / Path(*portable_path.parts)).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"configured path escapes the project root: {relative_path}")
    return resolved


class StrictConfigModel(BaseModel):
    """Base model that rejects undocumented configuration fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectSettings(StrictConfigModel):
    """Project identity and keyed-comparison settings."""

    name: str
    key: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if _PROJECT_NAME_PATTERN.fullmatch(name) is None:
            raise ValueError("project name must be a lowercase snake_case identifier")
        return name

    @field_validator("key")
    @classmethod
    def canonicalize_key(cls, value: str) -> str:
        key = value.strip().upper()
        if _IDENTIFIER_PATTERN.fullmatch(key) is None:
            raise ValueError("project key must be a valid SAS identifier")
        return key


class SourceSettings(StrictConfigModel):
    """Ordered SAS programs and supporting macro files."""

    directory: str
    programs: list[str] = Field(min_length=1)
    macros: list[str] = Field(default_factory=list)

    @field_validator("directory")
    @classmethod
    def validate_directory(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @field_validator("programs")
    @classmethod
    def validate_programs(cls, values: list[str]) -> list[str]:
        programs = [_validate_filename(value, ".sas") for value in values]
        _validate_unique_case_insensitive(programs, "SAS program filenames")
        return programs

    @field_validator("macros")
    @classmethod
    def validate_macros(cls, values: list[str]) -> list[str]:
        macros = [_validate_filename(value, ".sas") for value in values]
        _validate_unique_case_insensitive(macros, "SAS macro filenames")
        return macros


class InputSettings(StrictConfigModel):
    """Portable paths for equivalent CSV and SAS input datasets."""

    csv: str
    sas7bdat: str

    @field_validator("csv")
    @classmethod
    def validate_csv_path(cls, value: str) -> str:
        path = _normalize_relative_path(value)
        if not path.lower().endswith(".csv"):
            raise ValueError("CSV input path must end with .csv")
        return path

    @field_validator("sas7bdat")
    @classmethod
    def validate_sas_path(cls, value: str) -> str:
        path = _normalize_relative_path(value)
        if not path.lower().endswith(".sas7bdat"):
            raise ValueError("SAS input path must end with .sas7bdat")
        return path


class ReferenceArtifact(StrictConfigModel):
    """Logical artifact name and its trusted file in each supplied format."""

    name: str
    csv_filename: str
    sas7bdat_filename: str

    @field_validator("name")
    @classmethod
    def canonicalize_name(cls, value: str) -> str:
        name = value.strip().upper()
        if _IDENTIFIER_PATTERN.fullmatch(name) is None:
            raise ValueError("artifact name must be a valid SAS identifier")
        return name

    @field_validator("csv_filename")
    @classmethod
    def validate_csv_filename(cls, value: str) -> str:
        return _validate_filename(value, ".csv")

    @field_validator("sas7bdat_filename")
    @classmethod
    def validate_sas_filename(cls, value: str) -> str:
        return _validate_filename(value, ".sas7bdat")


class ReferenceSettings(StrictConfigModel):
    """Trusted reference directories, authority, and logical artifacts."""

    csv_directory: str
    sas7bdat_directory: str
    preferred_numeric_source: Literal["csv", "sas7bdat"] = "sas7bdat"
    artifacts: list[ReferenceArtifact] = Field(min_length=1)

    @field_validator("csv_directory", "sas7bdat_directory")
    @classmethod
    def validate_directory(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @model_validator(mode="after")
    def validate_unique_artifacts(self) -> Self:
        _validate_unique_case_insensitive(
            [artifact.name for artifact in self.artifacts], "artifact names"
        )
        _validate_unique_case_insensitive(
            [artifact.csv_filename for artifact in self.artifacts], "CSV filenames"
        )
        _validate_unique_case_insensitive(
            [artifact.sas7bdat_filename for artifact in self.artifacts],
            "SAS7BDAT filenames",
        )
        return self


class RepairSettings(StrictConfigModel):
    """Bounded settings reserved for the future repair loop."""

    max_attempts: int = Field(ge=0, le=3)


class ProjectConfiguration(StrictConfigModel):
    """Versioned definition of one SAS migration case study."""

    schema_version: Literal[1] = 1
    project: ProjectSettings
    source: SourceSettings
    input: InputSettings
    reference: ReferenceSettings
    repair: RepairSettings

    def resolve_paths(self, project_root: Path) -> ResolvedProjectPaths:
        """Resolve all configured paths beneath a repository root."""
        root = project_root.resolve()
        source_directory = _resolve_beneath(root, self.source.directory)
        reference_csv_directory = _resolve_beneath(root, self.reference.csv_directory)
        reference_sas_directory = _resolve_beneath(root, self.reference.sas7bdat_directory)

        return ResolvedProjectPaths(
            project_root=root,
            source_directory=source_directory,
            programs=tuple(source_directory / name for name in self.source.programs),
            macros=tuple(source_directory / name for name in self.source.macros),
            input_csv=_resolve_beneath(root, self.input.csv),
            input_sas7bdat=_resolve_beneath(root, self.input.sas7bdat),
            reference_csv_directory=reference_csv_directory,
            reference_sas7bdat_directory=reference_sas_directory,
            reference_csv={
                artifact.name: reference_csv_directory / artifact.csv_filename
                for artifact in self.reference.artifacts
            },
            reference_sas7bdat={
                artifact.name: reference_sas_directory / artifact.sas7bdat_filename
                for artifact in self.reference.artifacts
            },
        )


@dataclass(frozen=True, slots=True)
class ResolvedProjectPaths:
    """Absolute paths derived from a validated project configuration."""

    project_root: Path
    source_directory: Path
    programs: tuple[Path, ...]
    macros: tuple[Path, ...]
    input_csv: Path
    input_sas7bdat: Path
    reference_csv_directory: Path
    reference_sas7bdat_directory: Path
    reference_csv: dict[str, Path]
    reference_sas7bdat: dict[str, Path]

    def require_existing(self) -> None:
        """Raise a clear error listing every configured path that is missing."""
        directories = (
            self.source_directory,
            self.reference_csv_directory,
            self.reference_sas7bdat_directory,
        )
        files = (
            *self.programs,
            *self.macros,
            self.input_csv,
            self.input_sas7bdat,
            *self.reference_csv.values(),
            *self.reference_sas7bdat.values(),
        )
        missing_directories = [path for path in directories if not path.is_dir()]
        missing_files = [path for path in files if not path.is_file()]
        if missing_directories or missing_files:
            missing = sorted(
                path.relative_to(self.project_root).as_posix()
                for path in (*missing_directories, *missing_files)
            )
            raise FileNotFoundError(
                "configured project paths are missing:\n- " + "\n- ".join(missing)
            )


def load_project_configuration(
    config_path: Path,
    *,
    project_root: Path,
    require_existing: bool = True,
) -> ProjectConfiguration:
    """Load a strict YAML configuration and validate its repository paths."""
    with config_path.open(encoding="utf-8") as stream:
        payload: Any = yaml.safe_load(stream)

    configuration = ProjectConfiguration.model_validate(payload)
    paths = configuration.resolve_paths(project_root)
    if require_existing:
        paths.require_existing()
    return configuration
