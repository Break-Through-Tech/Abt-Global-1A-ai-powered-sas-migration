"""CLI tests for the bounded human-reference Mortality prototype."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import sasguard.cli as cli
from sasguard.verification import ArtifactComparison, ReferenceSource

runner = CliRunner()


def comparison(*, passed: bool) -> ArtifactComparison:
    """Build a compact comparison result without reading supplied artifacts."""
    return ArtifactComparison(
        artifact="OUTCOME_MORTALITY",
        passed=passed,
        reference_source=ReferenceSource.SAS7BDAT,
        expected_rows=2,
        actual_rows=2,
        expected_columns=["PROVIDER_ID", "DEATH_FLAG"],
        actual_columns=["PROVIDER_ID", "DEATH_FLAG"],
        mismatched_cells=0 if passed else 1,
        mismatched_columns=[] if passed else ["DEATH_FLAG"],
    )


def test_mortality_cli_reports_scope_and_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "comparison.json"
    received: dict[str, object] = {}

    def fake_run(project_root: Path, *, image: str) -> tuple[ArtifactComparison, Path]:
        received["project_root"] = project_root
        received["image"] = image
        return comparison(passed=True), report_path

    monkeypatch.setattr(cli, "run_mortality_prototype", fake_run)

    result = runner.invoke(
        cli.app,
        ["mortality-prototype", "--project-root", str(tmp_path), "--image", "runner:test"],
    )

    assert result.exit_code == 0
    assert "Mortality prototype passed" in result.stdout
    assert "Program 1 Mortality only, supplied Program 0 intermediate" in result.stdout
    assert str(report_path) in result.stdout
    assert "PROVIDER_ID" not in result.stdout
    assert received == {"project_root": tmp_path, "image": "runner:test"}


def test_mortality_cli_returns_one_for_comparison_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "comparison.json"
    monkeypatch.setattr(
        cli,
        "run_mortality_prototype",
        lambda project_root, *, image: (comparison(passed=False), report_path),
    )

    result = runner.invoke(cli.app, ["mortality-prototype", "--project-root", str(tmp_path)])

    assert result.exit_code == 1
    assert "comparison failed" in result.stdout
    assert str(report_path) in result.stdout
    assert "DEATH_FLAG" not in result.stdout


def test_mortality_cli_returns_two_when_execution_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_run(project_root: Path, *, image: str) -> tuple[ArtifactComparison, Path]:
        raise RuntimeError("Mortality execution failed: failed; see reports/runs/mortality-test")

    monkeypatch.setattr(cli, "run_mortality_prototype", failed_run)

    result = runner.invoke(cli.app, ["mortality-prototype", "--project-root", str(tmp_path)])

    assert result.exit_code == 2
    assert "Mortality prototype could not run" in result.stderr
    assert "Mortality execution failed" in result.stderr
