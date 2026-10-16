"""Configured input and reference access through the canonical artifact loader."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import pandas as pd

from sasguard.columns import resolve_column_name
from sasguard.config import ResolvedProjectPaths
from sasguard.data import load_artifact

DEFAULT_KEY = "PROVIDER_ID"


def resolve_column(columns: Iterable[str], name: str) -> str:
    """Resolve a column case-insensitively, rejecting missing or ambiguous names."""
    return resolve_column_name(name, list(columns))


def load_csv(path: Path, *, key: str | None = DEFAULT_KEY) -> pd.DataFrame:
    """Read CSV through the shared loader and require the requested key if given."""
    if path.suffix.casefold() != ".csv":
        raise ValueError("load_csv requires a .csv file")
    return load_artifact(path, key=key).frame


def load_sas7bdat(path: Path, *, key: str | None = DEFAULT_KEY) -> pd.DataFrame:
    """Read SAS7BDAT through the shared loader without coercing numeric IDs."""
    if path.suffix.casefold() != ".sas7bdat":
        raise ValueError("load_sas7bdat requires a .sas7bdat file")
    return load_artifact(path, key=key).frame


def load_canonical(path: Path, *, key: str | None = DEFAULT_KEY) -> pd.DataFrame:
    """Load either supported format with uppercase column names."""
    return load_artifact(path, key=key).frame


def _require_source(source: str) -> None:
    if source not in ("csv", "sas7bdat"):
        raise ValueError("source must be csv or sas7bdat")


def load_input(
    paths: ResolvedProjectPaths, *, source: Literal["csv", "sas7bdat"], key: str = DEFAULT_KEY
) -> pd.DataFrame:
    """Load the configured input dataset and require its comparison key."""
    _require_source(source)
    file_path = paths.input_csv if source == "csv" else paths.input_sas7bdat
    return load_canonical(file_path, key=key)


def load_reference_artifact(
    paths: ResolvedProjectPaths,
    name: str,
    *,
    source: Literal["csv", "sas7bdat"] = "sas7bdat",
    key: str | None = None,
) -> pd.DataFrame:
    """Load a named reference, including summary tables without provider IDs."""
    _require_source(source)
    catalog = paths.reference_csv if source == "csv" else paths.reference_sas7bdat
    resolved = resolve_column(catalog.keys(), name)
    return load_canonical(catalog[resolved], key=key)
