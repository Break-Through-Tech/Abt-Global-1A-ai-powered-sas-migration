"""Validate Program 0 output CSVs against the supplied SAS artifacts (#44)."""

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pandas as pd
import pyreadstat
import pytest

from sasguard.config import load_project_configuration
from sasguard.program0 import translate_program0
from sasguard.provenance.hashing import sha256_file
from sasguard.verification.integrity import load_and_verify_integrity
from sasguard.verification.program0 import (
    PROGRAM0_ARTIFACTS,
    load_program0_policies,
    validate_program0_outputs,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "configs" / "cms_2025jul.yaml"
MANIFEST_PATH = PROJECT_ROOT / "configs" / "protected-artifacts.json"
ANALYSIS = "std_data_2025jul_analysis.csv"


@pytest.fixture(scope="module", autouse=True)
def protected_artifacts_remain_unchanged() -> Iterator[None]:
    yield
    result = load_and_verify_integrity(PROJECT_ROOT, MANIFEST_PATH)
    assert result.passed, (
        f"protected artifacts changed: modified={result.modified_files}, "
        f"missing={result.missing_files}, unexpected={result.unexpected_files}"
    )


@pytest.fixture(scope="module")
def reference_outputs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Write the human-reference outputs the same way `sasguard run-program0` does."""
    paths = load_project_configuration(CONFIG_PATH, project_root=PROJECT_ROOT).resolve_paths(
        PROJECT_ROOT
    )
    source, _ = pyreadstat.read_sas7bdat(paths.input_sas7bdat)
    result = translate_program0(source)
    directory = tmp_path_factory.mktemp("program0-reference")
    frames = (result.excluded_measures, result.raw_statistics, result.analysis)
    for name, frame in zip(PROGRAM0_ARTIFACTS, frames, strict=True):
        frame.to_csv(directory / name, index=False, float_format="%.17g")
    return directory


@pytest.fixture
def outputs(reference_outputs: Path, tmp_path: Path) -> Path:
    """Give each test its own copy so tests can change files independently."""
    directory = tmp_path / "output"
    shutil.copytree(reference_outputs, directory)
    return directory


def hashes(directory: Path) -> dict[str, str]:
    return {name: sha256_file(directory / name) for name in PROGRAM0_ARTIFACTS}


def rewrite_analysis(directory: Path, change: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
    path = directory / ANALYSIS
    frame = pd.read_csv(path, dtype={"PROVIDER_ID": str}, float_precision="round_trip")
    change(frame).to_csv(path, index=False, float_format="%.17g")


def test_policies_cover_exactly_the_three_artifacts() -> None:
    policies = load_program0_policies(PROJECT_ROOT)

    assert set(policies) == set(PROGRAM0_ARTIFACTS.values())
    assert policies["LESS100_MEASURE"].keys == ("MEASURE_NAME",)
    assert policies["MEASURE_AVERAGE_STDDEV_2025JUL"].keys == ("_STAT_",)
    assert policies["STD_DATA_2025JUL_ANALYSIS"].keys == ("PROVIDER_ID",)


def test_human_reference_passes_all_three_checks(outputs: Path) -> None:
    result = validate_program0_outputs(PROJECT_ROOT, outputs, hashes(outputs))

    assert result.status == "passed", result.errors
    assert result.passed
    assert set(result.artifact_results) == set(PROGRAM0_ARTIFACTS)
    for filename, comparison in result.artifact_results.items():
        assert comparison.passed, f"{filename}: {comparison.mismatched_columns}"
        assert comparison.artifact == PROGRAM0_ARTIFACTS[filename]
        assert comparison.reference_source.value == "sas7bdat"
    assert result.artifact_results[ANALYSIS].expected_rows == 4566


def test_semantic_error_runs_but_fails_with_the_affected_column(outputs: Path) -> None:
    """Forgetting to reverse one lower-is-better measure is a plausible translation bug."""

    def forget_reversal(frame: pd.DataFrame) -> pd.DataFrame:
        frame["std_MORT_30_AMI"] = -frame["std_MORT_30_AMI"]
        return frame

    rewrite_analysis(outputs, forget_reversal)

    result = validate_program0_outputs(PROJECT_ROOT, outputs, hashes(outputs))

    assert result.status == "failed"
    analysis = result.artifact_results[ANALYSIS]
    assert not analysis.passed
    # The shared loader canonicalizes SAS names to uppercase.
    assert analysis.mismatched_columns == ["STD_MORT_30_AMI"]
    assert analysis.mismatched_cells > 0
    assert analysis.missingness_mismatches == 0
    assert result.artifact_results["measure_average_stddev_2025jul.csv"].passed


def test_dropped_hospital_is_reported_as_a_missing_key(outputs: Path) -> None:
    rewrite_analysis(outputs, lambda frame: frame.iloc[1:])

    result = validate_program0_outputs(PROJECT_ROOT, outputs, hashes(outputs))

    assert result.status == "failed"
    analysis = result.artifact_results[ANALYSIS]
    assert len(analysis.missing_keys) == 1
    assert analysis.actual_rows == 4565


def test_missing_output_is_reported_without_comparisons(outputs: Path) -> None:
    recorded = hashes(outputs)
    (outputs / ANALYSIS).unlink()

    result = validate_program0_outputs(PROJECT_ROOT, outputs, recorded)

    assert result.status == "missing_outputs"
    assert set(result.errors) == {ANALYSIS}
    assert result.artifact_results == {}


def test_output_changed_after_collection_is_a_hash_mismatch(outputs: Path) -> None:
    recorded = hashes(outputs)
    with (outputs / "less100_measure.csv").open("a", encoding="utf-8") as stream:
        stream.write("0,OP_99\n")

    result = validate_program0_outputs(PROJECT_ROOT, outputs, recorded)

    assert result.status == "hash_mismatch"
    assert set(result.errors) == {"less100_measure.csv"}
    assert result.artifact_results == {}


def test_unreadable_output_is_malformed(outputs: Path) -> None:
    rewrite_analysis(outputs, lambda frame: pd.concat([frame, frame.iloc[:1]]))

    result = validate_program0_outputs(PROJECT_ROOT, outputs, hashes(outputs))

    assert result.status == "malformed_outputs"
    assert "duplicate" in result.errors[ANALYSIS]
    assert result.artifact_results == {}


def test_hash_mapping_must_name_exactly_the_three_outputs(outputs: Path) -> None:
    recorded = hashes(outputs)
    del recorded[ANALYSIS]

    with pytest.raises(ValueError, match="exactly these outputs"):
        validate_program0_outputs(PROJECT_ROOT, outputs, recorded)


@pytest.mark.parametrize("statistic,delta", [("N", 1e-9), ("MIN", 1e-13), ("MAX", 1e-13)])
def test_small_changes_to_exact_statistics_fail(
    outputs: Path, statistic: str, delta: float
) -> None:
    path = outputs / "measure_average_stddev_2025jul.csv"
    frame = pd.read_csv(path, float_precision="round_trip")
    frame.loc[frame["_STAT_"].eq(statistic), "MORT_30_AMI"] += delta
    frame.to_csv(path, index=False, float_format="%.17g")
    result = validate_program0_outputs(PROJECT_ROOT, outputs, hashes(outputs))
    assert result.status == "failed"
    comparison = result.artifact_results[path.name]
    assert comparison.mismatched_columns == ["MORT_30_AMI"]
    assert comparison.mismatched_cells == 1
    assert comparison.expected_rows == comparison.actual_rows == 5
