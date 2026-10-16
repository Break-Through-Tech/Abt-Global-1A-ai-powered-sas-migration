"""Declared CMS checkpoint relationships, without loading protected output rows."""

from pathlib import Path

from sasguard.config import load_project_configuration
from sasguard.verification import ArtifactLineage

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def configured_lineage() -> ArtifactLineage:
    return ArtifactLineage.model_validate_json(
        (PROJECT_ROOT / "configs/cms-artifact-lineage.json").read_text(encoding="utf-8")
    )


def test_declared_graph_covers_all_catalogued_reference_artifacts() -> None:
    config = load_project_configuration(
        PROJECT_ROOT / "configs/cms_2025jul.yaml", project_root=PROJECT_ROOT
    )
    lineage = configured_lineage()
    references = {artifact.name for artifact in config.reference.artifacts}
    assert set(lineage.ordered_names()) == references | {"ALLDATA_2025JUL"}


def test_measure_summary_and_standardization_are_observational_siblings() -> None:
    lineage = configured_lineage()
    parents = {node.name: set(node.parents) for node in lineage.nodes}
    common = {"ALLDATA_2025JUL", "LESS100_MEASURE"}
    assert parents["STD_DATA_2025JUL_ANALYSIS"] == common
    assert parents["MEASURE_AVERAGE_STDDEV_2025JUL"] == common
    assert "MEASURE_AVERAGE_STDDEV_2025JUL" not in lineage.ancestors("STD_DATA_2025JUL_ANALYSIS")


def test_star_and_national_average_keep_all_declared_input_branches() -> None:
    lineage = configured_lineage()
    parents = {node.name: set(node.parents) for node in lineage.nodes}
    domains = {"OUTCOME_MORTALITY", "OUTCOME_SAFETY", "OUTCOME_READMISSION", "PTEXP", "PROCESS"}
    assert all(parents[domain] == {"STD_DATA_2025JUL_ANALYSIS"} for domain in domains)
    assert parents["STAR_2025JUL"] == domains | {"STD_DATA_2025JUL_ANALYSIS"}
    assert parents["NATIONAL_AVERAGE_2025JUL"] == domains | {"STAR_2025JUL"}
