"""Compare the Program 0 translation with the supplied SAS output artifacts."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
import pytest

from sasguard.config import load_project_configuration
from sasguard.program0 import translate_program0
from sasguard.verification.integrity import load_and_verify_integrity

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "configs" / "cms_2025jul.yaml"
MANIFEST_PATH = PROJECT_ROOT / "configs" / "protected-artifacts.json"
ABSOLUTE_TOLERANCE = 1e-12
RELATIVE_TOLERANCE = 1e-12


def read_sas(path: Path) -> pd.DataFrame:
    data, _ = pyreadstat.read_sas7bdat(path)
    return data


@pytest.fixture(scope="module", autouse=True)
def protected_artifacts_remain_unchanged() -> Iterator[None]:
    yield
    result = load_and_verify_integrity(PROJECT_ROOT, MANIFEST_PATH)
    assert result.passed, (
        f"protected artifacts changed: modified={result.modified_files}, "
        f"missing={result.missing_files}, unexpected={result.unexpected_files}"
    )


def assert_numeric_column_equal(actual: pd.Series, expected: pd.Series, name: str) -> None:
    assert actual.isna().tolist() == expected.isna().tolist(), f"{name}: missingness differs"
    np.testing.assert_allclose(
        actual.to_numpy(dtype=float),
        expected.to_numpy(dtype=float),
        rtol=RELATIVE_TOLERANCE,
        atol=ABSOLUTE_TOLERANCE,
        equal_nan=True,
        err_msg=f"{name}: values differ",
    )


def assert_exact_numeric_column(actual: pd.Series, expected: pd.Series, name: str) -> None:
    assert np.array_equal(
        actual.to_numpy(dtype=float), expected.to_numpy(dtype=float), equal_nan=True
    ), f"{name}: passthrough values differ"


def test_all_three_program0_outputs_match_supplied_sas() -> None:
    paths = load_project_configuration(CONFIG_PATH, project_root=PROJECT_ROOT).resolve_paths(
        PROJECT_ROOT
    )
    source = read_sas(paths.input_sas7bdat)
    result = translate_program0(source)
    excluded = read_sas(paths.reference_sas7bdat["LESS100_MEASURE"])
    statistics = read_sas(paths.reference_sas7bdat["MEASURE_AVERAGE_STDDEV_2025JUL"])
    analysis = read_sas(paths.reference_sas7bdat["STD_DATA_2025JUL_ANALYSIS"])

    assert list(result.excluded_measures.columns) == list(excluded.columns)
    assert result.excluded_measures.shape == excluded.shape
    assert result.excluded_measures.to_dict("records") == excluded.to_dict("records")

    assert list(result.raw_statistics.columns) == list(statistics.columns)
    assert result.raw_statistics.shape == statistics.shape
    assert result.raw_statistics["_STAT_"].tolist() == statistics["_STAT_"].tolist()
    for name in statistics.columns.drop("_STAT_"):
        assert_numeric_column_equal(result.raw_statistics[name], statistics[name], name)
        assert_exact_numeric_column(
            result.raw_statistics[name].iloc[:3], statistics[name].iloc[:3], name
        )

    assert list(result.analysis.columns) == list(analysis.columns)
    assert result.analysis.shape == analysis.shape
    assert result.analysis["PROVIDER_ID"].tolist() == analysis["PROVIDER_ID"].tolist()
    for name in analysis.columns.drop("PROVIDER_ID"):
        if name.startswith("std_"):
            assert_numeric_column_equal(result.analysis[name], analysis[name], name)
        else:
            assert_exact_numeric_column(result.analysis[name], analysis[name], name)
