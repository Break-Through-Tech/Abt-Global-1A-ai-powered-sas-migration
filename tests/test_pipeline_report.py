"""Reports for saved full-pipeline validation runs."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from sasguard.config import load_project_configuration
from sasguard.data import load_artifact
from sasguard.prototypes.pipeline_reference import run_human_program0, run_human_program1
from sasguard.reporting import write_run_report
from sasguard.reporting.pipeline import read_pipeline_report
from sasguard.verification.pipeline import (
    DOMAIN_SCORE_COLUMNS,
    StageInput,
    StageSource,
    render_summary,
    validate_pipeline,
)

ROOT = Path(__file__).resolve().parents[1]
FAKE_KEY = "sk-abcdefghijklmnop1234"


def _write(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, float_format="%.17g")


def _program2_control(program1: Path, destination: Path) -> None:
    """SAS stars and averages with the actual Program 1 scores copied in (a test control)."""
    paths = load_project_configuration(
        ROOT / "configs/cms_2025jul.yaml", project_root=ROOT
    ).resolve_paths(ROOT)
    destination.mkdir(parents=True, exist_ok=True)
    star = load_artifact(paths.reference_sas7bdat["STAR_2025JUL"], key="PROVIDER_ID").frame.copy()
    for domain, column in DOMAIN_SCORE_COLUMNS.items():
        frame = load_artifact(program1 / f"{domain.lower()}.csv", key="PROVIDER_ID").frame
        star[column] = star["PROVIDER_ID"].map(frame.set_index("PROVIDER_ID")["GRP_SCORE"])
    _write(star, destination / "star_2025jul.csv")
    _write(
        load_artifact(paths.reference_sas7bdat["NATIONAL_AVERAGE_2025JUL"]).frame,
        destination / "national_average_2025jul.csv",
    )


@pytest.fixture(scope="module")
def chain(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("pipeline-report-chain")
    run_human_program0(ROOT, base / "program0")
    run_human_program1(ROOT, base / "program0", base / "program1")
    _program2_control(base / "program1", base / "program2")
    return base


def saved_run(
    chain: Path,
    project: Path,
    *,
    keep_program2: bool = True,
    empty: bool = False,
    note: str = "",
) -> Path:
    run = project / "reports/runs/pipeline-test"
    run.mkdir(parents=True)
    names = ("program0", "program1", "program2")
    for name in names:
        if empty or (name == "program2" and not keep_program2):
            (run / name).mkdir()
        else:
            shutil.copytree(chain / name, run / name)
    sources = (
        StageSource.HUMAN_REFERENCE,
        StageSource.HUMAN_REFERENCE,
        StageSource.HELPER_ASSISTED_MODEL_OUTPUT,
    )
    result = validate_pipeline(
        ROOT,
        *(
            StageInput(source=source, output_directory=run / name, note=note)
            for name, source in zip(names, sources, strict=True)
        ),
    )
    (run / "pipeline-validation.json").write_text(result.model_dump_json(indent=2) + "\n")
    (run / "summary.md").write_text(render_summary(result))
    return run


def report(project: Path, run: Path) -> tuple[dict, str, str]:
    target = write_run_report(project, run, output_directory=Path("reports/runs/out"))
    return (
        json.loads((target / "report.json").read_text()),
        (target / "handoff.md").read_text(),
        (target / "technical.md").read_text(),
    )


def test_pass_run_is_verified_with_counts_and_distribution(chain: Path, tmp_path: Path) -> None:
    run = saved_run(chain, tmp_path)
    data, cms, technical = report(tmp_path, run)
    assert data["scope_status"] == "VERIFIED"
    assert data["report_kind"] == "pipeline"
    assert data["artifacts_passed"] == 10
    assert data["hospitals_processed"] and data["hospitals_eligible"]
    assert sum(data["star_distribution"].values()) <= data["hospitals_processed"]
    assert data["human_review"] == "not_recorded"
    assert "Validation status: VERIFIED" in cms
    assert "| Star rating | Hospitals |" in cms
    assert "helper-assisted model output" in cms
    assert "human reference" in cms
    assert "29/29 (passed)" in technical
    assert "OUTCOME_MORTALITY" in technical
    assert "Human review: not recorded" in technical


def test_partial_run_is_not_verified_and_has_no_distribution(chain: Path, tmp_path: Path) -> None:
    run = saved_run(chain, tmp_path, keep_program2=False)
    data, cms, technical = report(tmp_path, run)
    assert data["scope_status"] == "NOT VERIFIED"
    assert data["star_distribution"] is None
    assert data["hospitals_processed"] is None
    assert "Validation status: NOT VERIFIED" in cms
    assert "must not be used as such" in cms
    assert "Star rating" not in cms
    assert "Earliest divergence" in technical


def test_failed_run_is_failed(chain: Path, tmp_path: Path) -> None:
    run = saved_run(chain, tmp_path, empty=True)
    data, cms, _ = report(tmp_path, run)
    assert data["scope_status"] == "FAILED"
    assert "Validation status: FAILED" in cms
    assert "Star rating" not in cms


def test_tampered_output_fails_and_is_named(chain: Path, tmp_path: Path) -> None:
    run = saved_run(chain, tmp_path)
    target = run / "program1" / "ptexp.csv"
    target.write_bytes(target.read_bytes() + b"\n")
    data, cms, _ = report(tmp_path, run)
    assert data["scope_status"] == "FAILED"
    assert any("output_changed_since_record" in item for item in data["evidence_issues"])
    assert "Star rating" not in cms


def test_edited_record_status_is_not_trusted(chain: Path, tmp_path: Path) -> None:
    run = saved_run(chain, tmp_path, keep_program2=False)
    path = run / "pipeline-validation.json"
    record = json.loads(path.read_text())
    record["status"] = "PASS"
    record["full_pipeline_parity"] = True
    path.write_text(json.dumps(record))
    data, _, _ = report(tmp_path, run)
    assert data["scope_status"] == "FAILED"
    assert "record_status_disagrees_with_its_artifact_results" in data["evidence_issues"]


def test_secret_like_notes_are_not_rendered(
    chain: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOME_API_KEY", FAKE_KEY)
    run = saved_run(chain, tmp_path, note=f"used api_key={FAKE_KEY} locally")
    _, cms, technical = report(tmp_path, run)
    everything = cms + technical + (tmp_path / "reports/runs/out/report.json").read_text()
    assert FAKE_KEY not in everything
    assert "[redacted]" in technical
    commit = read_pipeline_report(tmp_path, run).environment["git_commit"]
    assert commit in technical


def test_other_layouts_still_unsupported(tmp_path: Path) -> None:
    run = tmp_path / "reports/runs/unknown"
    run.mkdir(parents=True)
    with pytest.raises(ValueError, match="unsupported run layout"):
        write_run_report(tmp_path, run)
