"""Tests for the one-command `sasguard demo`."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from sasguard import cli
from sasguard.cli import app

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "reports" / "runs"


def test_demo_happy_path_passes_and_writes_evidence_and_reports() -> None:
    before = set(RUNS.iterdir()) if RUNS.exists() else set()
    try:
        outcome = CliRunner().invoke(app, ["demo", "--project-root", str(ROOT)])
        created = set(RUNS.iterdir()) - before
        assert outcome.exit_code == 0, outcome.output
        assert "Status: PASS. 10 of 10 artifact comparisons passed." in outcome.output
        assert "STAR mismatches: 0." in outcome.output
        assert "pending teammate review" in outcome.output
        evidence = next(p for p in created if p.name.startswith("pipeline-"))
        reports = next(p for p in created if p.name.startswith("handoff-"))
        assert f"Evidence: {evidence}" in outcome.output
        assert (evidence / "pipeline-validation.json").is_file()
        assert (evidence / "summary.md").is_file()
        files = sorted(p.name for p in reports.iterdir() if p.is_file())
        assert {"report.json", "handoff.md", "technical.md"} <= set(files)
        for name in files:
            assert f"  {name}" in outcome.output
    finally:
        for path in set(RUNS.iterdir()) - before:
            shutil.rmtree(path, ignore_errors=True)


def test_demo_stops_on_integrity_failure_without_running_the_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = SimpleNamespace(
        passed=False,
        checked_files=3,
        missing_files=["data/missing.csv"],
        modified_files=["data/changed.csv"],
        unexpected_files=[],
    )
    monkeypatch.setattr(cli, "load_and_verify_integrity", lambda root, manifest: failed)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("pipeline must not run after an integrity failure")

    monkeypatch.setattr(cli, "_record_pipeline_validation", forbidden)
    outcome = CliRunner().invoke(app, ["demo", "--project-root", str(ROOT)])
    assert outcome.exit_code == 1
    assert "integrity check failed" in outcome.output
    assert "Missing: data/missing.csv" in outcome.output
    assert "Modified: data/changed.csv" in outcome.output


def test_demo_non_pass_exits_one_but_still_writes_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = cli._record_pipeline_validation
    before = set(RUNS.iterdir()) if RUNS.exists() else set()

    def partial(*args: Any, **kwargs: Any) -> Any:
        result, run, summary = real(*args, **kwargs)
        result = result.model_copy(update={"status": "PARTIAL", "artifacts_passed": 9})
        (run / "pipeline-validation.json").write_text(
            result.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return result, run, summary

    monkeypatch.setattr(cli, "_record_pipeline_validation", partial)
    try:
        outcome = CliRunner().invoke(app, ["demo", "--project-root", str(ROOT)])
        created = set(RUNS.iterdir()) - before
        assert outcome.exit_code == 1, outcome.output
        assert "Status: PARTIAL. 9 of 10 artifact comparisons passed." in outcome.output
        reports = next(p for p in created if p.name.startswith("handoff-"))
        assert (reports / "report.json").is_file()
        assert "Reports:" in outcome.output
    finally:
        for path in set(RUNS.iterdir()) - before:
            shutil.rmtree(path, ignore_errors=True)


def test_demo_setup_error_exits_two(tmp_path: Path) -> None:
    outcome = CliRunner().invoke(app, ["demo", "--project-root", str(tmp_path)])
    assert outcome.exit_code == 2
