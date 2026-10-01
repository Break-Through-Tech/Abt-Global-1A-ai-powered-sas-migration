"""Regression tests for known facts about the supplied CMS July 2025 artifacts.

These tests only read supplied files. If one fails, either a supplied artifact
changed or code that reads them changed; neither should happen silently.
The expected values are documented in docs/artifact-inventory.md.
"""

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pyreadstat
import pytest

from sasguard.config import ResolvedProjectPaths, load_project_configuration
from sasguard.verification.integrity import load_and_verify_integrity

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "configs" / "cms_2025jul.yaml"
INTEGRITY_MANIFEST_PATH = PROJECT_ROOT / "configs" / "protected-artifacts.json"

PROVIDER_ID_COLUMN = "PROVIDER_ID"

# Input dataset
EXPECTED_PROVIDER_COUNT = 4566
EXPECTED_INPUT_COLUMN_COUNT = 93
EXPECTED_PROVIDER_ID_LENGTH = 6
EXPECTED_PROVIDER_IDS_WITH_LEADING_ZERO = 710
EXPECTED_PROVIDER_IDS_WITH_LETTERS = 131

# Measures
EXPECTED_MEASURE_COUNT = 46
EXPECTED_EXCLUDED_MEASURE_COUNT = 0
MEANS_STATISTIC_COLUMNS = {"_TYPE_", "_FREQ_", "_STAT_"}

# Star ratings
EXPECTED_RATED_HOSPITAL_COUNT = 2891
EXPECTED_STAR_DISTRIBUTION = {1: 233, 2: 661, 3: 939, 4: 767, 5: 291}
EXPECTED_PEER_GROUP_COUNTS = {
    "1) # of groups=3": 141,
    "2) # of groups=4": 515,
    "3) # of groups=5": 2235,
}


@pytest.fixture(scope="module")
def paths() -> ResolvedProjectPaths:
    """Resolve supplied artifact paths from the checked-in project configuration."""
    configuration = load_project_configuration(CONFIG_PATH, project_root=PROJECT_ROOT)
    return configuration.resolve_paths(PROJECT_ROOT)


@pytest.fixture(scope="module", autouse=True)
def supplied_artifacts_stay_unchanged() -> Iterator[None]:
    """Fail the module if any test modified, removed, or added a protected file."""
    yield
    result = load_and_verify_integrity(PROJECT_ROOT, INTEGRITY_MANIFEST_PATH)
    assert result.passed, (
        "regression tests changed protected artifacts: "
        f"modified={result.modified_files}, missing={result.missing_files}, "
        f"unexpected={result.unexpected_files}"
    )


def read_sas(path: Path) -> pd.DataFrame:
    """Read a supplied SAS binary dataset."""
    frame, _ = pyreadstat.read_sas7bdat(path)
    return frame


@pytest.fixture(scope="module")
def input_csv(paths: ResolvedProjectPaths) -> pd.DataFrame:
    # dtype=str keeps provider identifiers exactly as supplied, including leading zeros.
    return pd.read_csv(paths.input_csv, dtype=str)


@pytest.fixture(scope="module")
def input_sas(paths: ResolvedProjectPaths) -> pd.DataFrame:
    return read_sas(paths.input_sas7bdat)


@pytest.fixture(scope="module")
def star(paths: ResolvedProjectPaths) -> pd.DataFrame:
    return read_sas(paths.reference_sas7bdat["STAR_2025JUL"])


@pytest.mark.parametrize("source", ["input_csv", "input_sas"])
def test_input_has_expected_provider_and_column_counts(
    source: str, request: pytest.FixtureRequest
) -> None:
    frame: pd.DataFrame = request.getfixturevalue(source)
    providers, columns = frame.shape

    assert providers == EXPECTED_PROVIDER_COUNT, (
        f"{source}: expected {EXPECTED_PROVIDER_COUNT} providers, found {providers}"
    )
    assert columns == EXPECTED_INPUT_COLUMN_COUNT, (
        f"{source}: expected {EXPECTED_INPUT_COLUMN_COUNT} columns, found {columns}"
    )


def test_provider_ids_are_unique_six_character_text(input_csv: pd.DataFrame) -> None:
    ids = input_csv[PROVIDER_ID_COLUMN]

    assert ids.notna().all(), "every provider must have a PROVIDER_ID"
    assert ids.is_unique, f"duplicate PROVIDER_IDs: {ids[ids.duplicated()].tolist()[:5]}"
    wrong_length = ids[ids.str.len() != EXPECTED_PROVIDER_ID_LENGTH]
    assert wrong_length.empty, (
        f"PROVIDER_IDs must have {EXPECTED_PROVIDER_ID_LENGTH} characters; "
        f"found {wrong_length.tolist()[:5]}"
    )


def test_provider_ids_keep_leading_zeros_and_letters(input_csv: pd.DataFrame) -> None:
    """Numeric parsing would drop leading zeros and fail on alphanumeric IDs."""
    ids = input_csv[PROVIDER_ID_COLUMN]
    leading_zero = int(ids.str.startswith("0").sum())
    with_letters = int(ids.str.contains(r"[A-Za-z]", regex=True).sum())

    assert leading_zero == EXPECTED_PROVIDER_IDS_WITH_LEADING_ZERO, (
        f"expected {EXPECTED_PROVIDER_IDS_WITH_LEADING_ZERO} PROVIDER_IDs with a leading "
        f"zero, found {leading_zero}"
    )
    assert with_letters == EXPECTED_PROVIDER_IDS_WITH_LETTERS, (
        f"expected {EXPECTED_PROVIDER_IDS_WITH_LETTERS} alphanumeric PROVIDER_IDs, "
        f"found {with_letters}"
    )


def test_csv_and_sas_inputs_contain_the_same_providers(
    input_csv: pd.DataFrame, input_sas: pd.DataFrame
) -> None:
    csv_ids = set(input_csv[PROVIDER_ID_COLUMN])
    sas_ids = set(input_sas[PROVIDER_ID_COLUMN])

    assert csv_ids == sas_ids, (
        f"provider sets differ: only in CSV={sorted(csv_ids - sas_ids)[:5]}, "
        f"only in SAS={sorted(sas_ids - csv_ids)[:5]}"
    )


def test_expected_measure_count(paths: ResolvedProjectPaths) -> None:
    statistics = read_sas(paths.reference_sas7bdat["MEASURE_AVERAGE_STDDEV_2025JUL"])
    measures = [column for column in statistics.columns if column not in MEANS_STATISTIC_COLUMNS]

    assert len(measures) == EXPECTED_MEASURE_COUNT, (
        f"expected {EXPECTED_MEASURE_COUNT} measures, found {len(measures)}"
    )


def test_standardized_analysis_file_has_every_measure(paths: ResolvedProjectPaths) -> None:
    analysis = read_sas(paths.reference_sas7bdat["STD_DATA_2025JUL_ANALYSIS"])
    standardized = [column for column in analysis.columns if column.lower().startswith("std_")]

    assert len(standardized) == EXPECTED_MEASURE_COUNT, (
        f"expected {EXPECTED_MEASURE_COUNT} standardized measures, found {len(standardized)}"
    )


def test_no_measures_are_excluded(paths: ResolvedProjectPaths) -> None:
    """No measure was reported by 100 or fewer hospitals in the July 2025 release."""
    excluded = read_sas(paths.reference_sas7bdat["LESS100_MEASURE"])

    assert len(excluded) == EXPECTED_EXCLUDED_MEASURE_COUNT, (
        f"expected {EXPECTED_EXCLUDED_MEASURE_COUNT} excluded measures, found "
        f"{len(excluded)}: {excluded.get('measure_name', pd.Series(dtype=str)).tolist()}"
    )


def test_expected_rated_hospital_count(star: pd.DataFrame) -> None:
    rated = star["report_indicator"] == 1
    rated_count = int(rated.sum())

    assert rated_count == EXPECTED_RATED_HOSPITAL_COUNT, (
        f"expected {EXPECTED_RATED_HOSPITAL_COUNT} rated hospitals, found {rated_count}"
    )
    stars_without_rating = int((star["star"].notna() & ~rated).sum())
    ratings_without_star = int((star["star"].isna() & rated).sum())
    assert stars_without_rating == 0, (
        f"{stars_without_rating} hospitals have a star but report_indicator != 1"
    )
    assert ratings_without_star == 0, (
        f"{ratings_without_star} hospitals have report_indicator = 1 but no star"
    )


def test_expected_star_distribution(star: pd.DataFrame) -> None:
    counts = star["star"].dropna().astype(int).value_counts().sort_index().to_dict()

    assert counts == EXPECTED_STAR_DISTRIBUTION, (
        f"expected star counts {EXPECTED_STAR_DISTRIBUTION}, found {counts}"
    )


def test_expected_peer_group_counts(star: pd.DataFrame) -> None:
    rated = star[star["report_indicator"] == 1]
    counts = rated["cnt_grp"].str.strip().value_counts().sort_index().to_dict()

    assert counts == EXPECTED_PEER_GROUP_COUNTS, (
        f"expected peer-group counts {EXPECTED_PEER_GROUP_COUNTS}, found {counts}"
    )
    unrated_groups = star.loc[star["report_indicator"] != 1, "cnt_grp"].str.strip()
    assert (unrated_groups == "").all(), "unrated hospitals must not be assigned a peer group"
