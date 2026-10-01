"""Tests for canonical input and reference-data loaders."""

from pathlib import Path

import pandas as pd
import pytest

from sasguard.config import load_project_configuration
from sasguard.loaders import (
    load_input,
    load_reference_artifact,
    resolve_column,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "cms_2025jul.yaml"


@pytest.fixture(scope="module")
def paths():
    configuration = load_project_configuration(CONFIG_PATH, project_root=PROJECT_ROOT)
    return configuration.resolve_paths(PROJECT_ROOT)


def test_provider_id_preserves_leading_zeros_csv(paths) -> None:
    frame = load_input(paths, source="csv")
    assert frame["PROVIDER_ID"].iloc[0] == "010001"


def test_provider_id_preserves_leading_zeros_sas7bdat(paths) -> None:
    frame = load_input(paths, source="sas7bdat")
    assert frame["PROVIDER_ID"].iloc[0] == "010001"


def test_csv_and_sas7bdat_load_successfully(paths) -> None:
    csv_frame = load_input(paths, source="csv")
    sas_frame = load_input(paths, source="sas7bdat")
    assert len(csv_frame) == len(sas_frame) > 0


def test_case_insensitive_column_resolution() -> None:
    columns = ["Provider_Id", "Claim_Amt"]
    assert resolve_column(columns, "provider_id") == "Provider_Id"
    assert resolve_column(columns, "PROVIDER_ID") == "Provider_Id"


def test_case_insensitive_resolution_missing_column_raises() -> None:
    with pytest.raises(KeyError):
        resolve_column(["Claim_Amt"], "provider_id")


def test_missing_numeric_values_are_not_coerced_to_zero(paths) -> None:
    frame = load_input(paths, source="csv")
    # EDAC_30_AMI is blank for provider 010005 in the supplied fixture.
    row = frame.loc[frame["PROVIDER_ID"] == "010005", "EDAC_30_AMI"]
    assert pd.isna(row.iloc[0])
    assert row.iloc[0] != 0


def test_reference_artifact_without_identifier_loads(paths) -> None:
    # NATIONAL_AVERAGE_2025JUL has no PROVIDER_ID column; the loader must
    # not require one.
    frame = load_reference_artifact(paths, "NATIONAL_AVERAGE_2025JUL", source="csv")
    assert "PROVIDER_ID" not in frame.columns
    assert len(frame) > 0


def test_reference_artifact_with_identifier_preserves_it(paths) -> None:
    frame = load_reference_artifact(paths, "STAR_2025JUL", source="sas7bdat")
    assert frame["PROVIDER_ID"].dtype == "string"
