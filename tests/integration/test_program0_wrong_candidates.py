"""Executable but wrong Program 0 candidates must be rejected (#45)."""

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pyreadstat
import pytest

from sasguard.config import load_project_configuration
from sasguard.program0 import CMS_2025_JUL, Program0Spec, translate_program0
from sasguard.provenance.hashing import sha256_file
from sasguard.verification.integrity import load_and_verify_integrity
from sasguard.verification.program0 import PROGRAM0_ARTIFACTS, validate_program0_outputs

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "configs" / "cms_2025jul.yaml"
MANIFEST_PATH = PROJECT_ROOT / "configs" / "protected-artifacts.json"
ANALYSIS = "std_data_2025jul_analysis.csv"


@pytest.fixture(scope="module", autouse=True)
def protected_artifacts_remain_unchanged() -> Iterator[None]:
    yield
    result = load_and_verify_integrity(PROJECT_ROOT, MANIFEST_PATH)
    assert result.passed


@pytest.fixture(scope="module")
def source() -> pd.DataFrame:
    paths = load_project_configuration(CONFIG_PATH, project_root=PROJECT_ROOT).resolve_paths(
        PROJECT_ROOT
    )
    frame, _ = pyreadstat.read_sas7bdat(paths.input_sas7bdat)
    return frame


def run_candidate(directory: Path, data: pd.DataFrame, spec: Program0Spec = CMS_2025_JUL):
    """Run a wrong candidate (it must not raise), write its CSVs, and validate them."""
    result = translate_program0(data, spec=spec)
    frames = (result.excluded_measures, result.raw_statistics, result.analysis)
    for name, frame in zip(PROGRAM0_ARTIFACTS, frames, strict=True):
        frame.to_csv(directory / name, index=False, float_format="%.17g")
    hashes = {name: sha256_file(directory / name) for name in PROGRAM0_ARTIFACTS}
    return validate_program0_outputs(PROJECT_ROOT, directory, hashes)


def test_skipped_direction_reversal_is_rejected(tmp_path: Path, source: pd.DataFrame) -> None:
    spec = Program0Spec(measures=CMS_2025_JUL.measures, reversed_measures=frozenset())

    result = run_candidate(tmp_path, source, spec)

    assert result.status == "failed"
    analysis = result.artifact_results[ANALYSIS]
    assert not analysis.passed
    assert analysis.mismatched_cells > 0
    assert all(name.startswith("STD_") for name in analysis.mismatched_columns)


def test_missing_values_changed_to_zero_are_rejected(tmp_path: Path, source: pd.DataFrame) -> None:
    data = source.copy()
    measure_columns = [c for c in data.columns if c.upper() in CMS_2025_JUL.measures]
    data[measure_columns] = data[measure_columns].fillna(0)

    result = run_candidate(tmp_path, data)

    assert result.status == "failed"
    assert not result.artifact_results[ANALYSIS].passed


def test_leading_zero_provider_ids_lost_are_rejected(tmp_path: Path, source: pd.DataFrame) -> None:
    data = source.copy()
    id_column = next(c for c in data.columns if c.upper() == "PROVIDER_ID")
    data[id_column] = pd.to_numeric(data[id_column], errors="coerce").astype("Int64")

    result = run_candidate(tmp_path, data)

    assert result.status == "malformed_outputs"
    assert set(result.errors) == {ANALYSIS}
    assert result.artifact_results == {}