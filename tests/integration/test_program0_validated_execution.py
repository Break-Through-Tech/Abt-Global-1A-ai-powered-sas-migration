"""Execute human-reference controls in Docker, then validate on the host with real SAS."""

import os
import shutil
from pathlib import Path

import pytest

from sasguard.execution.manifest import RunManifest
from sasguard.execution.program0 import (
    CandidateInputFormat,
    CandidateReport,
    CandidateStatus,
    run_program0_candidate,
    validate_collected_program0,
)
from sasguard.provenance.hashing import sha256_file
from sasguard.reporting import write_run_report
from sasguard.reporting.models import ScopeStatus
from sasguard.reporting.reader import read_run_report
from sasguard.verification.integrity import load_and_verify_integrity

pytestmark = pytest.mark.docker_integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mistake", [None, "N", "MIN", "MAX", "reversal", "csv_precision"])
def test_reference_control_and_wrong_candidates_use_real_validator(
    tmp_path: Path, mistake: str | None
) -> None:
    if os.environ.get("SASGUARD_RUN_DOCKER_TESTS") != "1" or shutil.which("docker") is None:
        pytest.skip("set SASGUARD_RUN_DOCKER_TESTS=1 with Docker available")
    # This is a human-written control, not a model attempt. Only its standalone source
    # and the hospital CSV enter Docker. SAS references remain on the host.
    source = (ROOT / "src/sasguard/program0.py").read_text(encoding="utf-8")
    entry = """
import os
from pathlib import Path
input_directory = Path(os.environ["SASGUARD_INPUT_DIR"])
output_directory = Path(os.environ["SASGUARD_OUTPUT_DIR"])
input_frame = pd.read_csv(input_directory / "alldata_2025jul.csv",
                          converters={"PROVIDER_ID": str}, float_precision="round_trip")
result = translate_program0(input_frame)
"""
    if mistake == "reversal":
        entry += 'result.analysis["std_MORT_30_AMI"] = -result.analysis["std_MORT_30_AMI"]\n'
    elif mistake in ("N", "MIN", "MAX"):
        delta = "1e-9" if mistake == "N" else "1e-13"
        entry += (
            f'statistic_row = result.raw_statistics["_STAT_"].eq({mistake!r})\n'
            f'result.raw_statistics.loc[statistic_row, "MORT_30_AMI"] += {delta}\n'
        )
    entry += """
for name, frame in (
    ("less100_measure.csv", result.excluded_measures),
    ("measure_average_stddev_2025jul.csv", result.raw_statistics),
    ("std_data_2025jul_analysis.csv", result.analysis),
):
    frame.to_csv(output_directory / name, index=False, float_format="%.17g")
"""
    candidate = tmp_path / "human_reference_control.py"
    candidate.write_text(source + "\n" + entry, encoding="utf-8")
    input_format = (
        CandidateInputFormat.CSV if mistake == "csv_precision" else CandidateInputFormat.SAS7BDAT
    )
    report, path = run_program0_candidate(
        ROOT,
        candidate,
        image="sasguard-runner:test",
        validator=validate_collected_program0,
        input_format=input_format,
    )
    assert report.execution_result is not None and report.execution_result.passed
    assert report.status is CandidateStatus.READY
    assert report.input_format is input_format
    assert report.validation_status == ("passed" if mistake is None else "failed"), (
        report.validation_error,
        report.validation_errors,
        {name: value.mismatched_columns for name, value in report.validation_results.items()},
    )
    assert len(report.validation_results) == 3
    assert report.validation_results["std_data_2025jul_analysis.csv"].expected_rows == 4566
    if mistake is not None:
        artifact = (
            "std_data_2025jul_analysis.csv"
            if mistake == "reversal"
            else "measure_average_stddev_2025jul.csv"
        )
        comparison = report.validation_results[artifact]
        assert not comparison.passed
        if mistake == "csv_precision":
            assert "MORT_30_AMI" in comparison.mismatched_columns
        else:
            assert comparison.mismatched_columns == [
                "STD_MORT_30_AMI" if mistake == "reversal" else "MORT_30_AMI"
            ]
    assert CandidateReport.model_validate_json(path.read_bytes()) == report
    assert report.human_review == "not_recorded"
    assert report.validation_evidence is not None
    summary = read_run_report(ROOT, path.parent)
    assert summary.scope_status is (ScopeStatus.VERIFIED if mistake is None else ScopeStatus.FAILED)
    assert summary.input_format == input_format.value
    assert summary.code_origin == summary.generation_status == "not_recorded"
    assert summary.evidence_integrity == "matched", summary.evidence_issues
    destination = write_run_report(ROOT, path.parent)
    assert "Full-pipeline status: NOT VERIFIED" in (destination / "handoff.md").read_text()
    staged = path.parent / "input/alldata_2025jul.csv"
    assert sorted(item.name for item in staged.parent.iterdir()) == [
        "alldata_2025jul.csv",
        "contract.json",
    ]
    manifest = RunManifest.model_validate_json((path.parent / "manifest.json").read_bytes())
    input_relative = "data/Project_1/Starrating/alldata_2025jul." + input_format.value
    assert manifest.input_hashes == {input_relative: sha256_file(ROOT / input_relative)}
    assert load_and_verify_integrity(ROOT, ROOT / "configs/protected-artifacts.json").passed
