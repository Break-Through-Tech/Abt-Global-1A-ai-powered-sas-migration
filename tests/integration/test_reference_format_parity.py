"""Check that the supplied STAR table has matching missing text across formats."""

from pathlib import Path

from sasguard.config import load_project_configuration
from sasguard.data import load_artifact
from sasguard.verification import (
    ArtifactComparisonPolicy,
    NumericTolerance,
    compare_artifacts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_star_sas_and_csv_outputs_compare_without_false_missingness() -> None:
    configuration = load_project_configuration(
        PROJECT_ROOT / "configs" / "cms_2025jul.yaml", project_root=PROJECT_ROOT
    )
    paths = configuration.resolve_paths(PROJECT_ROOT)
    expected = load_artifact(paths.reference_sas7bdat["STAR_2025JUL"], key="PROVIDER_ID")
    actual = load_artifact(paths.reference_csv["STAR_2025JUL"], key="PROVIDER_ID")

    result = compare_artifacts(
        actual,
        expected,
        artifact="STAR_2025JUL",
        policy=ArtifactComparisonPolicy(
            keys=("PROVIDER_ID",),
            default_numeric_tolerance=NumericTolerance(absolute=1e-6),
        ),
    )

    assert result.passed
    assert result.missingness_mismatches == 0
    assert result.mismatched_cells == 0
