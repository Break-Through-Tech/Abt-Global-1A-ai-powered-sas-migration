"""A second CMS release runs through the full pipeline from configuration alone.

The synthetic ``2026jan`` release is the July 2025 data with every release-tagged file renamed.
It proves that nothing on the pipeline path reads a July-named file or name; it is not a real
second release. The temporary project root contains no ``2025jul`` file at all.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from sasguard.cli import app
from sasguard.config import ProjectConfiguration, load_project_configuration, load_release
from sasguard.release import JULY_2025, ROLE_TEMPLATES, Release, validate_tag
from sasguard.reporting import write_run_report
from sasguard.reporting.pipeline import read_pipeline_report
from sasguard.verification.integrity import build_integrity_manifest
from sasguard.verification.pipeline import (
    PipelineValidation,
    ReleaseRecord,
    audit_policies,
    release_of,
)
from sasguard.verification.program0 import load_program0_policies
from sasguard.verification.program1 import load_program1_policies
from sasguard.verification.program2 import load_program2_policies

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "configs/cms_2026jan.yaml"
MANIFEST = "configs/protected-artifacts-2026jan.json"
JAN_2026 = Release(tag="2026jan", integrity_manifest=MANIFEST, config_path=CONFIG)
JULY_ARTIFACTS = {
    "LESS100_MEASURE",
    "MEASURE_AVERAGE_STDDEV_2025JUL",
    "STD_DATA_2025JUL_ANALYSIS",
    "OUTCOME_MORTALITY",
    "OUTCOME_READMISSION",
    "OUTCOME_SAFETY",
    "PTEXP",
    "PROCESS",
    "STAR_2025JUL",
    "NATIONAL_AVERAGE_2025JUL",
}


def _retag(text: str) -> str:
    """Rename the July 2025 tag to 2026jan, keeping each occurrence's letter case."""
    cases = {"jul": "jan", "JUL": "JAN", "Jul": "Jan"}
    return re.sub(r"2025(jul)", lambda m: "2026" + cases[m.group(1)], text, flags=re.IGNORECASE)


def _retag_value(value: Any) -> Any:
    if isinstance(value, str):
        return _retag(value)
    if isinstance(value, list):
        return [_retag_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _retag_value(item) for key, item in value.items()}
    return value


def _build_project(base: Path) -> Path:
    """Copy what the pipeline needs, renaming every release-tagged file to ``2026jan``."""
    root = base / "project"
    (root / "configs").mkdir(parents=True)
    for name in (
        "program0-comparison-policies.json",
        "program1-comparison-policies.json",
        "program2-comparison-policies.json",
    ):
        shutil.copy2(ROOT / "configs" / name, root / "configs" / name)
    shutil.copytree(ROOT / "reference_python", root / "reference_python")
    for source in (ROOT / "data/Project_1").rglob("*"):
        if source.is_file():
            relative = source.relative_to(ROOT)
            target = root / relative.parent / _retag(relative.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    payload = yaml.safe_load((ROOT / "configs/cms_2025jul.yaml").read_text(encoding="utf-8"))
    payload = _retag_value(payload)
    payload["release"] = {"tag": "2026jan", "integrity_manifest": MANIFEST}
    (root / CONFIG).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    manifest = build_integrity_manifest(root, ["data/Project_1"])
    (root / MANIFEST).write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def jan_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _build_project(tmp_path_factory.mktemp("release-2026jan"))


def _invoke(*arguments: str) -> tuple[int, str]:
    outcome = CliRunner().invoke(app, list(arguments))
    return outcome.exit_code, outcome.output


def _line(output: str, prefix: str) -> str:
    return next(
        line.removeprefix(prefix).strip() for line in output.splitlines() if line.startswith(prefix)
    )


@pytest.fixture(scope="module")
def pipeline_run(jan_project: Path) -> tuple[int, str, Path]:
    code, output = _invoke(
        "validate-pipeline",
        "--config",
        CONFIG,
        "--run-human-references",
        "--run-reference-program2",
        "--project-root",
        str(jan_project),
    )
    return code, output, Path(_line(output, "Evidence:"))


@pytest.fixture(scope="module")
def demo_run(jan_project: Path) -> tuple[int, str, Path]:
    code, output = _invoke("demo", "--config", CONFIG, "--project-root", str(jan_project))
    return code, output, Path(_line(output, "Reports:"))


def test_project_has_no_july_2025_file(jan_project: Path) -> None:
    names = [path.name.casefold() for path in jan_project.rglob("*")]
    assert not [name for name in names if "2025jul" in name]
    assert any("star_2026jan" in name for name in names)
    assert (jan_project / "data/Project_1/Starrating/alldata_2026jan.csv").is_file()


def test_pipeline_passes_for_the_new_release(
    jan_project: Path, pipeline_run: tuple[int, str, Path]
) -> None:
    code, output, run = pipeline_run
    assert code == 0, output
    assert "Status: PASS. 10 of 10 artifact comparisons passed." in output
    assert "STAR mismatches: 0." in output
    assert "established for the supplied 2026JAN SAS artifacts" in output
    record = PipelineValidation.model_validate_json(
        (run / "pipeline-validation.json").read_text(encoding="utf-8")
    )
    assert record.status == "PASS"
    assert record.star_mismatches == 0
    assert record.integrity_before["passed"] and record.integrity_after["passed"]
    artifacts = {outcome.artifact for stage in record.stages for outcome in stage.artifacts}
    assert artifacts == JAN_2026.artifact_names
    assert {"STAR_2026JAN", "NATIONAL_AVERAGE_2026JAN", "STD_DATA_2026JAN_ANALYSIS"} <= artifacts
    assert not any("2025" in name for name in artifacts)
    assert (run / "program2/star_2026jan.csv").is_file()
    assert not list(run.rglob("*2025jul*"))
    assert record.scope == "CMS 2026JAN; supplied SAS artifacts only"
    assert record.release is not None
    assert record.release.tag == "2026jan"
    assert record.release.config_path == CONFIG
    assert record.release.integrity_manifest == MANIFEST
    config_digest = record.release.config_sha256
    assert config_digest is not None and len(config_digest) == 64
    # The integrity check used the release's manifest: the default one is not in this project.
    assert not (jan_project / "configs/protected-artifacts.json").exists()
    assert record.integrity_before["expected_files"] == len(
        json.loads((jan_project / MANIFEST).read_text(encoding="utf-8"))["files"]
    )


def test_report_names_the_new_release_and_is_verified(
    jan_project: Path, pipeline_run: tuple[int, str, Path]
) -> None:
    _, _, run = pipeline_run
    target = write_run_report(jan_project, run, output_directory=Path("reports/runs/jan-report"))
    data = json.loads((target / "report.json").read_text(encoding="utf-8"))
    assert data["scope_status"] == "VERIFIED"
    assert data["artifacts_passed"] == 10
    assert data["input_release"] == "CMS Hospital Star Ratings, 2026JAN"
    assert data["hospitals_processed"] and data["star_distribution"] is not None
    assert not data["evidence_issues"] and not data["unverified_evidence"]
    assert set(data["release_files"]) == {
        f"{CONFIG} (config)",
        f"{MANIFEST} (integrity manifest)",
    }
    assert any("STAR_2026JAN" in row["artifact"] for row in data["artifacts"])
    texts = {name: (target / name).read_text(encoding="utf-8") for name in sorted_files(target)}
    for name, text in texts.items():
        if name == "report.json":
            continue
        assert "July 2025" not in text, name
        assert "2025JUL" not in text.upper(), name
    assert "STAR_2026JAN" in texts["technical.md"]
    assert "hospital star ratings: pipeline validation summary" in texts["handoff.md"]
    assert "CMS 2026JAN hospital star ratings" in texts["handoff.md"]
    assert "any release other than 2026JAN" in texts["handoff.md"]


def sorted_files(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir() if entry.is_file())


def test_demo_runs_the_new_release_end_to_end(demo_run: tuple[int, str, Path]) -> None:
    code, output, report = demo_run
    assert code == 0, output
    assert "Integrity check passed:" in output
    assert "Status: PASS. 10 of 10 artifact comparisons passed." in output
    assert "STAR mismatches: 0." in output
    assert "Report status: VERIFIED." in output
    data = json.loads((report / "report.json").read_text(encoding="utf-8"))
    assert data["scope_status"] == "VERIFIED"
    assert data["input_release"] == "CMS Hospital Star Ratings, 2026JAN"
    assert "STAR_2026JAN" in (report / "technical.md").read_text(encoding="utf-8")


def test_tampered_reference_fails_integrity_through_the_config_manifest(
    jan_project: Path, tmp_path: Path
) -> None:
    root = tmp_path / "project"
    shutil.copytree(jan_project, root)
    target = root / "data/Project_1/SAS Output CSV/STAR_2026JAN.csv"
    target.write_bytes(target.read_bytes() + b"tampered\n")

    code, output = _invoke(
        "validate-pipeline",
        "--config",
        CONFIG,
        "--run-human-references",
        "--run-reference-program2",
        "--project-root",
        str(root),
    )
    assert code == 1
    assert "Status: FAIL" in output
    assert "Protected-file integrity before / after:" in output
    assert "(failed)" in output
    assert f"Earliest divergence: integrity, artifact {MANIFEST}" in output
    run = Path(_line(output, "Evidence:"))
    record = json.loads((run / "pipeline-validation.json").read_text(encoding="utf-8"))
    assert record["integrity_before"]["passed"] is False
    assert record["status"] == "FAIL"

    code, output = _invoke("demo", "--config", CONFIG, "--project-root", str(root))
    assert code == 1
    assert "Demo stopped: protected-file integrity check failed." in output
    assert "Modified: data/Project_1/SAS Output CSV/STAR_2026JAN.csv" in output


def test_missing_config_exits_with_a_setup_error(jan_project: Path) -> None:
    code, output = _invoke(
        "demo", "--config", "configs/missing.yaml", "--project-root", str(jan_project)
    )
    assert code == 2
    assert "Configuration could not be loaded" in output


def test_report_reader_rejects_a_record_that_lost_its_release(
    jan_project: Path, pipeline_run: tuple[int, str, Path]
) -> None:
    """Without the release block a record means July 2025, so 2026JAN artifacts do not fit."""
    _, _, run = pipeline_run
    stripped = jan_project / "reports/runs" / f"stripped-{uuid.uuid4()}"
    shutil.copytree(run, stripped)
    path = stripped / "pipeline-validation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["release"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = read_pipeline_report(jan_project, stripped)
    assert report.scope_status == "FAILED"
    assert "record_artifacts_do_not_belong_to_its_release" in report.evidence_issues


@pytest.fixture(scope="module")
def july_run() -> Any:
    """A default-configuration July 2025 run in the repository, removed afterwards."""
    run = ROOT / "reports" / "runs" / f"pipeline-test-{uuid.uuid4()}"
    code, output = _invoke(
        "validate-pipeline",
        "--run-human-references",
        "--run-reference-program2",
        "--output-directory",
        str(run),
    )
    try:
        yield code, output, run
    finally:
        shutil.rmtree(run, ignore_errors=True)


def test_default_run_records_the_july_release(july_run: tuple[int, str, Path]) -> None:
    code, output, run = july_run
    assert code == 0, output
    record = json.loads((run / "pipeline-validation.json").read_text(encoding="utf-8"))
    assert record["scope"] == "CMS July 2025; supplied SAS artifacts only"
    assert record["release"]["tag"] == "2025jul"
    assert record["release"]["config_path"] == "configs/cms_2025jul.yaml"
    assert record["release"]["integrity_manifest"] == "configs/protected-artifacts.json"
    assert "established for the supplied July 2025 SAS artifacts" in output
    assert (run / "program2/star_2025jul.csv").is_file()


def test_report_reader_still_accepts_a_record_without_a_release(
    july_run: tuple[int, str, Path],
) -> None:
    """Records written before releases were configurable carry no release block."""
    _, _, run = july_run
    legacy = ROOT / "reports" / "runs" / f"pipeline-test-{uuid.uuid4()}"
    shutil.copytree(run, legacy)
    try:
        path = legacy / "pipeline-validation.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        del payload["release"]
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report = read_pipeline_report(ROOT, legacy)
        assert report.scope_status == "VERIFIED"
        assert report.input_release == "CMS Hospital Star Ratings, July 2025"
        assert report.release_files == {}
        assert not report.evidence_issues
    finally:
        shutil.rmtree(legacy, ignore_errors=True)


# Unit tests: release helpers, tag validation, configuration, policy role mapping.


def test_default_release_derives_the_july_2025_names() -> None:
    assert JULY_2025.tag == "2025jul"
    assert {JULY_2025.artifact(role) for role in ROLE_TEMPLATES} == JULY_ARTIFACTS
    assert JULY_2025.artifact_names == JULY_ARTIFACTS
    assert JULY_2025.filename("STAR") == "star_2025jul.csv"
    assert JULY_2025.filename("LESS100_MEASURE") == "less100_measure.csv"
    assert JULY_2025.analysis_filename == "std_data_2025jul_analysis.csv"
    assert JULY_2025.input_filename == "alldata_2025jul.csv"
    assert JULY_2025.program0_artifacts == {
        "less100_measure.csv": "LESS100_MEASURE",
        "measure_average_stddev_2025jul.csv": "MEASURE_AVERAGE_STDDEV_2025JUL",
        "std_data_2025jul_analysis.csv": "STD_DATA_2025JUL_ANALYSIS",
    }
    assert JULY_2025.program2_artifacts == {
        "star_2025jul.csv": "STAR_2025JUL",
        "national_average_2025jul.csv": "NATIONAL_AVERAGE_2025JUL",
    }
    assert JULY_2025.label == "July 2025"
    assert JULY_2025.integrity_manifest == "configs/protected-artifacts.json"
    assert JULY_2025.config_path == "configs/cms_2025jul.yaml"


def test_release_derives_names_from_its_tag() -> None:
    release = Release(tag="2026jan")
    assert release.artifact("STAR") == "STAR_2026JAN"
    assert release.artifact("NATIONAL_AVERAGE") == "NATIONAL_AVERAGE_2026JAN"
    assert release.artifact("MEASURE_AVERAGE_STDDEV") == "MEASURE_AVERAGE_STDDEV_2026JAN"
    assert release.artifact("STD_DATA_ANALYSIS") == "STD_DATA_2026JAN_ANALYSIS"
    assert release.filename("STAR") == "star_2026jan.csv"
    assert release.filename("STD_DATA_ANALYSIS") == "std_data_2026jan_analysis.csv"
    assert release.input_filename == "alldata_2026jan.csv"
    assert release.label == "2026JAN"
    # Release-neutral roles carry no tag.
    for role in ("LESS100_MEASURE", "OUTCOME_MORTALITY", "OUTCOME_SAFETY", "PTEXP", "PROCESS"):
        assert release.artifact(role) == JULY_2025.artifact(role)
    assert release.role_of("STAR_2026JAN") == "STAR"
    assert release.role_of("PTEXP") == "PTEXP"
    with pytest.raises(KeyError):
        release.role_of("STAR_2025JUL")
    assert len(release.artifact_names) == 10
    assert release_of(_record_stub("2026jan")).tag == "2026jan"


def _record_stub(tag: str) -> PipelineValidation:
    release = ReleaseRecord(
        tag=tag,
        config_path=CONFIG,
        config_sha256=None,
        integrity_manifest=MANIFEST,
        integrity_manifest_sha256=None,
    )
    return PipelineValidation.model_construct(release=release)


@pytest.mark.parametrize("tag", ["2026JAN", "2026-jan", "2026_jan", "", "jan 2026", "../x", "é"])
def test_invalid_release_tags_are_rejected(tag: str) -> None:
    with pytest.raises(ValueError):
        validate_tag(tag)
    with pytest.raises(ValueError):
        Release(tag=tag)


@pytest.mark.parametrize("tag", ["2025jul", "2026jan", "r1", "abc123"])
def test_valid_release_tags_are_accepted(tag: str) -> None:
    assert validate_tag(tag) == tag


def _july_payload() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "configs/cms_2025jul.yaml").read_text(encoding="utf-8"))


def test_configuration_release_section_is_optional_and_defaults_to_july() -> None:
    assert "release" not in _july_payload()
    configuration = ProjectConfiguration.model_validate(_july_payload())
    assert configuration.release.tag == "2025jul"
    assert configuration.release.integrity_manifest == "configs/protected-artifacts.json"
    release = load_release(Path("configs/cms_2025jul.yaml"), project_root=ROOT)
    assert release == JULY_2025


def test_configuration_release_section_is_validated() -> None:
    payload = _july_payload()
    payload["release"] = {"tag": "2026jan"}
    parsed = ProjectConfiguration.model_validate(payload)
    assert parsed.release.tag == "2026jan"
    assert parsed.release.integrity_manifest == "configs/protected-artifacts.json"
    for bad in (
        {"tag": "2026JAN"},
        {"tag": "2026-jan"},
        {"integrity_manifest": "../outside.json"},
        {"integrity_manifest": "/abs/manifest.json"},
        {"integrity_manifest": "configs/manifest.txt"},
        {"unknown": "x"},
    ):
        payload["release"] = bad
        with pytest.raises(ValidationError):
            ProjectConfiguration.model_validate(payload)


def test_load_release_reads_the_config_and_rejects_paths_outside_the_root(
    jan_project: Path, tmp_path: Path
) -> None:
    assert load_release(Path(CONFIG), project_root=jan_project) == JAN_2026
    assert load_release(jan_project / CONFIG, project_root=jan_project) == JAN_2026
    outside = tmp_path / "cms.yaml"
    shutil.copy2(jan_project / CONFIG, outside)
    with pytest.raises(ValueError, match="inside the project root"):
        load_release(outside, project_root=jan_project)
    assert load_project_configuration(jan_project / CONFIG, project_root=jan_project)


def test_policies_apply_by_role_with_unchanged_tolerances() -> None:
    loaders = (load_program0_policies, load_program1_policies, load_program2_policies)
    for load in loaders:
        july = load(ROOT)
        jan = load(ROOT, JAN_2026)
        assert len(jan) == len(july)
        for name, policy in july.items():
            mapped = JAN_2026.artifact(JULY_2025.role_of(name))
            # The same policy object content: keys, columns and every tolerance.
            assert jan[mapped] == policy
            assert jan[mapped].model_dump() == policy.model_dump()
        assert set(jan) <= JAN_2026.artifact_names
    program2 = load_program2_policies(ROOT, JAN_2026)
    assert set(program2) == {"STAR_2026JAN", "NATIONAL_AVERAGE_2026JAN"}
    assert program2["STAR_2026JAN"] == load_program2_policies(ROOT)["STAR_2025JUL"]
    program0 = load_program0_policies(ROOT, JAN_2026)
    assert set(program0) == {
        "LESS100_MEASURE",
        "MEASURE_AVERAGE_STDDEV_2026JAN",
        "STD_DATA_2026JAN_ANALYSIS",
    }
    assert set(load_program1_policies(ROOT, JAN_2026)) == set(load_program1_policies(ROOT))


def test_policy_mapping_rejects_an_artifact_that_is_not_a_july_policy_key() -> None:
    with pytest.raises(KeyError):
        JAN_2026.policies_by_release_artifact({"STAR_2026JAN": object()})
    assert JAN_2026.policies_by_release_artifact({"STAR_2025JUL": 1}) == {"STAR_2026JAN": 1}


def test_policy_audit_still_checks_the_committed_policy_files(tmp_path: Path) -> None:
    """The audit reads the policy files by their own July keys, whichever release runs."""
    assert audit_policies(ROOT) == []
    shutil.copytree(ROOT / "configs", tmp_path / "configs")
    path = tmp_path / "configs/program2-comparison-policies.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["artifacts"]["STAR_2025JUL"]["default_numeric_tolerance"] = {
        "absolute": 1e-6,
        "relative": 1e-6,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    problems = audit_policies(tmp_path)
    assert problems and all("STAR_2025JUL" in problem for problem in problems)
