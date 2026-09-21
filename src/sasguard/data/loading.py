"""Read CSV and SAS7BDAT artifacts without changing identifier semantics."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd
import pyreadstat

from sasguard.columns import resolve_column_name


class ArtifactFormat(StrEnum):
    """Artifact formats supported by the canonical loader."""

    CSV = "csv"
    SAS7BDAT = "sas7bdat"


class ArtifactLoadError(ValueError):
    """Raised when an artifact cannot satisfy the loader contract."""


@dataclass(frozen=True, slots=True, eq=False)
class LoadedArtifact:
    """A loaded table plus the source and resolved comparison-key metadata."""

    frame: pd.DataFrame = field(repr=False)
    source_path: Path
    format: ArtifactFormat
    key_column: str

    @property
    def row_count(self) -> int:
        return len(self.frame.index)

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(self.frame.columns)


def _artifact_format(path: Path) -> ArtifactFormat:
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        return ArtifactFormat.CSV
    if suffix == ".sas7bdat":
        return ArtifactFormat.SAS7BDAT
    raise ArtifactLoadError(f"unsupported artifact format for {path.name!r}")


def _resolve_key(key: str, columns: list[str] | tuple[str, ...]) -> str:
    try:
        return resolve_column_name(key, columns)
    except (KeyError, ValueError) as error:
        raise ArtifactLoadError(str(error)) from error


def _read_csv_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream), None)
    if not header:
        raise ArtifactLoadError(f"CSV artifact has no header: {path.name}")
    return header


def _parse_text_key(value: str) -> object:
    """Preserve identifier text while representing an empty field as missing."""
    return pd.NA if value == "" else value


def _read_csv(path: Path, key: str) -> tuple[pd.DataFrame, str]:
    key_column = _resolve_key(key, _read_csv_header(path))
    frame = pd.read_csv(
        path,
        converters={key_column: _parse_text_key},
        low_memory=False,
    )
    return frame, key_column


def _read_sas7bdat(path: Path, key: str) -> tuple[pd.DataFrame, str]:
    loaded: tuple[pd.DataFrame, Any] = pyreadstat.read_sas7bdat(path)
    frame, _metadata = loaded
    key_column = _resolve_key(key, list(frame.columns))
    return frame, key_column


def _normalize_text_key(frame: pd.DataFrame, key_column: str, path: Path) -> pd.DataFrame:
    key_values = frame[key_column]
    nonmissing = key_values[key_values.notna()]
    if not nonmissing.map(lambda value: isinstance(value, str)).all():
        raise ArtifactLoadError(
            f"comparison key {key_column!r} must be textual in {path.name!r}; "
            "numeric identifiers cannot preserve leading zeros"
        )

    normalized = frame.copy(deep=False)
    normalized[key_column] = key_values.astype("string")
    return normalized


def load_artifact(path: Path, *, key: str) -> LoadedArtifact:
    """Load one artifact and preserve its textual comparison key and missing values."""
    source_path = path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"artifact file does not exist: {path}")

    artifact_format = _artifact_format(source_path)
    if artifact_format is ArtifactFormat.CSV:
        frame, key_column = _read_csv(source_path, key)
    else:
        frame, key_column = _read_sas7bdat(source_path, key)

    normalized = _normalize_text_key(frame, key_column, source_path)
    return LoadedArtifact(
        frame=normalized,
        source_path=source_path,
        format=artifact_format,
        key_column=key_column,
    )
