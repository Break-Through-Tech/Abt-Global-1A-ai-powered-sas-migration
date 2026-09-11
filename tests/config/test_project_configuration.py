"""Tests for the validated CMS project configuration."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from sasguard.config import ProjectConfiguration, load_project_configuration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "configs" / "cms_2025jul.yaml"


def read_config_payload() -> dict[str, Any]:
    """Load the checked-in YAML as a mutable dictionary for schema tests."""
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_cms_configuration_loads_and_resolves_all_supplied_paths() -> None:
    configuration = load_project_configuration(
        CONFIG_PATH,
        project_root=PROJECT_ROOT,
    )
    paths = configuration.resolve_paths(PROJECT_ROOT)

    assert configuration.project.name == "cms_star_2025jul"
    assert configuration.project.key == "PROVIDER_ID"
    assert configuration.repair.max_attempts == 3
    assert configuration.reference.preferred_numeric_source == "sas7bdat"
    assert [path.name for path in paths.programs] == [
        "0 - Data and Measure Standardization_2025Jul.sas",
        "1 - First stage_Simple Average of Measure Scores_2025Jul.sas",
        "2 - Second Stage_Weighted Average and Categorize Star_2025Jul.sas",
    ]
    assert [path.name for path in paths.macros] == ["Star_Macros.sas"]
    assert len(paths.reference_csv) == 10
    assert len(paths.reference_sas7bdat) == 10
    assert set(paths.reference_csv) == set(paths.reference_sas7bdat)


def test_all_ten_logical_artifacts_are_recorded_once() -> None:
    configuration = ProjectConfiguration.model_validate(read_config_payload())

    assert [artifact.name for artifact in configuration.reference.artifacts] == [
        "LESS100_MEASURE",
        "MEASURE_AVERAGE_STDDEV_2025JUL",
        "NATIONAL_AVERAGE_2025JUL",
        "OUTCOME_MORTALITY",
        "OUTCOME_READMISSION",
        "OUTCOME_SAFETY",
        "PROCESS",
        "PTEXP",
        "STAR_2025JUL",
        "STD_DATA_2025JUL_ANALYSIS",
    ]


@pytest.mark.parametrize(
    ("field", "unsafe_path"),
    [
        ("csv", "C:/private/input.csv"),
        ("csv", "/private/input.csv"),
        ("sas7bdat", "../input.sas7bdat"),
    ],
)
def test_absolute_and_escaping_input_paths_are_rejected(field: str, unsafe_path: str) -> None:
    payload = read_config_payload()
    payload["input"][field] = unsafe_path

    with pytest.raises(ValidationError, match="repository-relative"):
        ProjectConfiguration.model_validate(payload)


def test_undocumented_fields_are_rejected() -> None:
    payload = read_config_payload()
    payload["project"]["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProjectConfiguration.model_validate(payload)


def test_invalid_input_extension_is_rejected() -> None:
    payload = read_config_payload()
    payload["input"]["csv"] = "data/Project_1/Starrating/input.xlsx"

    with pytest.raises(ValidationError, match="must end with .csv"):
        ProjectConfiguration.model_validate(payload)


def test_repair_attempts_are_bounded_by_the_plan() -> None:
    payload = read_config_payload()
    payload["repair"]["max_attempts"] = 4

    with pytest.raises(ValidationError, match="less than or equal to 3"):
        ProjectConfiguration.model_validate(payload)


def test_duplicate_artifact_names_are_rejected_ignoring_case() -> None:
    payload = read_config_payload()
    duplicate = deepcopy(payload["reference"]["artifacts"][0])
    duplicate["name"] = duplicate["name"].lower()
    duplicate["csv_filename"] = "another.csv"
    duplicate["sas7bdat_filename"] = "another.sas7bdat"
    payload["reference"]["artifacts"].append(duplicate)

    with pytest.raises(ValidationError, match="artifact names must be unique"):
        ProjectConfiguration.model_validate(payload)


def test_paths_are_normalized_for_cross_platform_use() -> None:
    payload = read_config_payload()
    payload["source"]["directory"] = r"data\Project_1\SAS Programs"

    configuration = ProjectConfiguration.model_validate(payload)

    assert configuration.source.directory == "data/Project_1/SAS Programs"


def test_missing_configured_files_are_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="configured project paths are missing") as error:
        load_project_configuration(CONFIG_PATH, project_root=tmp_path)

    message = str(error.value)
    assert "data/Project_1/SAS Programs" in message
    assert "alldata_2025jul.csv" in message
    assert "STAR_2025JUL.csv" in message


def test_path_validation_can_be_deferred_for_planning(tmp_path: Path) -> None:
    configuration = load_project_configuration(
        CONFIG_PATH,
        project_root=tmp_path,
        require_existing=False,
    )

    assert configuration.project.key == "PROVIDER_ID"
