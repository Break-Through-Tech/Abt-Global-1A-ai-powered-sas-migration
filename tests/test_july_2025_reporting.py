from pathlib import Path
from uuid import uuid4

from sasguard.execution.result import ExecutionResult, ExecutionStatus
from sasguard.reporting.july_2025 import ReplayStage, write_replay_reports
from sasguard.reporting.models import ScopeStatus
from sasguard.verification.artifact import ArtifactComparison, ReferenceSource


def test_executable_wrong_ratings_are_never_included_in_the_client_draft(tmp_path: Path) -> None:
    execution = ExecutionResult(
        execution_id=uuid4(),
        status=ExecutionStatus.SUCCEEDED,
        exit_code=0,
        runtime_seconds=1,
        stdout="private runner log",
    )
    comparison = ArtifactComparison(
        artifact="STAR_2025JUL",
        passed=False,
        reference_source=ReferenceSource.SAS7BDAT,
        expected_rows=3,
        actual_rows=3,
        expected_columns=["PROVIDER_ID", "STAR"],
        actual_columns=["PROVIDER_ID", "STAR"],
        mismatched_cells=2,
        mismatched_columns=["STAR"],
        missing_keys=["private-provider-key"],
    )
    write_replay_reports(
        tmp_path,
        run_date="2026-11-17",
        status=ScopeStatus.FAILED,
        stages=[
            ReplayStage(execution, "passed", {}),
            ReplayStage(execution, "passed", {}),
            ReplayStage(execution, "failed", {comparison.artifact: comparison}),
        ],
        protected_files_checked=29,
        integrity_passed=True,
        totals=(3, 3, {1: 3}),
    )
    client = (tmp_path / "cms-summary.md").read_text(encoding="utf-8")
    technical = (tmp_path / "abt-validation.md").read_text(encoding="utf-8")
    assert "FAILED for the supplied CMS July 2025 release." in client
    assert "Star rating | Hospitals" not in client
    assert "First failed stage: Program 2 (STAR_2025JUL)." in technical
    assert "succeeded (exit 0) | failed" in technical
    assert "private runner log" not in client + technical
    assert "private-provider-key" not in client + technical
