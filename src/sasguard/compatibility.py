"""Bounded pandas helpers for ordinary SAS numeric missing values and CSV keys.

These helpers do not implement special missing values, SAS character comparisons,
formats, or a general SAS interpreter. They contain no evaluation fixtures.
"""

from __future__ import annotations

from math import isfinite
from pathlib import Path

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from sasguard.data import load_artifact


def read_sas_csv(path: Path, *, key: str | None = None) -> pd.DataFrame:
    """Read CSV with uppercase columns and a textual key protected from NA inference.

    PROVIDER_ID is the default key when present. Other character columns do not
    receive this protection. Empty numeric fields remain missing values.
    """
    if path.suffix.casefold() != ".csv":
        raise ValueError("read_sas_csv requires a CSV file")
    return load_artifact(path, key=key).frame.copy()


def _require_numeric(frame: pd.DataFrame) -> None:
    if any(not is_numeric_dtype(dtype) or is_bool_dtype(dtype) for dtype in frame.dtypes):
        raise ValueError("SAS numeric helpers require numeric, non-boolean columns")


def sas_lt(values: pd.Series[float], threshold: float) -> pd.Series[bool]:
    """Compare numeric values with a finite scalar, treating ordinary missing as lowest."""
    _require_numeric(values.to_frame())
    if not isfinite(threshold):
        raise ValueError("sas_lt requires a finite numeric threshold")
    return values.lt(threshold).fillna(False) | values.isna()


def sas_sum(values: pd.DataFrame) -> pd.Series[float]:
    """Evaluate row-wise SAS SUM for at least two numeric arguments.

    Ignore missing arguments unless all arguments are missing. Ordinary pandas
    addition should still be used for SAS arithmetic '+', which propagates missing.
    """
    if len(values.columns) < 2:
        raise ValueError("sas_sum requires at least two numeric argument columns")
    _require_numeric(values)
    return values.sum(axis=1, min_count=1)
