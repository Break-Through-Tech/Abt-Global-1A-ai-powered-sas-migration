"""Trusted loaders for canonical input and reference-data artifacts.

These are the single point where SASGuard reads supplied CSV and SAS7BDAT
files. They guarantee three properties required by CONTRIBUTING.md:
provider identifiers are preserved as strings (leading zeros intact), SAS
column names are resolved case-insensitively, and numeric missing values
are preserved as NaN rather than silently coerced to zero.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from pathlib import Path
from typing import Literal

import pandas as pd
import pyreadstat

from sasguard.config import ResolvedProjectPaths

DEFAULT_KEY = "PROVIDER_ID"


def resolve_column(columns: Iterable[str], name: str) -> str:
    """Resolve `name` to its actual column label, ignoring case.

    Raises `KeyError` if no column matches and `ValueError` if more than
    one column matches case-insensitively (the source data would itself
    violate the case-insensitive-uniqueness assumption).
    """
    matches = [c for c in columns if c.casefold() == name.casefold()]
    if not matches:
        raise KeyError(f"no column named {name!r} (case-insensitive) found")
    if len(matches) > 1:
        raise ValueError(f"multiple columns match {name!r} case-insensitively: {matches}")
    return matches[0]


def _try_resolve(columns: Iterable[str], name: str) -> str | None:
    """Like `resolve_column`, but returns None instead of raising when absent."""
    try:
        return resolve_column(columns, name)
    except KeyError:
        return None


def load_csv(path: Path, *, key: str | None = DEFAULT_KEY) -> pd.DataFrame:
    """Load a canonical CSV artifact.

    If `key` (e.g. PROVIDER_ID) is present, it is forced to string dtype
    before parsing so pandas cannot infer it as numeric and drop leading
    zeros. Not every artifact has a `key` column; pass `key=None` to skip
    the check, or rely on the default silently no-op-ing when absent.
    Empty numeric fields are left as NaN.
    """
    header = pd.read_csv(path, nrows=0).columns
    dtype: dict[Hashable, str] = {}
    if key is not None:
        resolved = _try_resolve(header, key)
        if resolved is not None:
            dtype[resolved] = "string"
    return pd.read_csv(path, dtype=dtype)


def load_sas7bdat(path: Path, *, key: str | None = DEFAULT_KEY) -> pd.DataFrame:
    """Load a canonical SAS7BDAT artifact.

    pyreadstat already maps SAS numeric missing codes to NaN and reads
    character variables as strings. The `key` column, if present, is
    defensively re-cast to string in case a future dataset stores it
    numerically.
    """
    frame, _meta = pyreadstat.read_sas7bdat(str(path))
    if key is not None:
        resolved = _try_resolve(frame.columns, key)
        if resolved is not None:
            frame[resolved] = frame[resolved].astype("string")
    return frame


def load_canonical(path: Path, *, key: str | None = DEFAULT_KEY) -> pd.DataFrame:
    """Dispatch to `load_csv` or `load_sas7bdat` based on file suffix."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_csv(path, key=key)
    if suffix == ".sas7bdat":
        return load_sas7bdat(path, key=key)
    raise ValueError(f"unsupported canonical artifact type: {path.suffix!r}")


def load_input(
    paths: ResolvedProjectPaths, *, source: Literal["csv", "sas7bdat"], key: str = DEFAULT_KEY
) -> pd.DataFrame:
    """Load the canonical input dataset in the requested format."""
    file_path = paths.input_csv if source == "csv" else paths.input_sas7bdat
    return load_canonical(file_path, key=key)


def load_reference_artifact(
    paths: ResolvedProjectPaths,
    name: str,
    *,
    source: Literal["csv", "sas7bdat"] = "sas7bdat",
    key: str = DEFAULT_KEY,
) -> pd.DataFrame:
    """Load one named trusted reference artifact in the requested format."""
    catalog = paths.reference_csv if source == "csv" else paths.reference_sas7bdat
    return load_canonical(catalog[name], key=key)
