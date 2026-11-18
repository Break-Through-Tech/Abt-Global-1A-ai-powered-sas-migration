"""Host-only reassessment of preserved synthetic outputs, without generation or execution."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from sasguard.data import load_artifact
from sasguard.execution.result import ExecutionResult
from sasguard.prototypes.local_model_validation import (
    VALIDATION_POLICY_VERSION,
    numeric_policy,
    select_cases,
)
from sasguard.provenance.hashing import normalize_relative_path, sha256_file, validate_sha256
from sasguard.verification import compare_artifacts


class SavedSuiteAttempt(BaseModel):
    model_config = ConfigDict(strict=True)

    model: str
    case: str
    passed: bool
    report: str


class SavedSuite(BaseModel):
    model_config = ConfigDict(strict=True)

    schema_version: Literal[1]
    complete: Literal[True]
    models: list[str] = Field(min_length=1)
    cases: list[str] = Field(min_length=1)
    attempts: list[SavedSuiteAttempt] = Field(min_length=1)


class SavedAttempt(BaseModel):
    model_config = ConfigDict(strict=True)

    schema_version: Literal[1]
    model: str
    case: str
    case_set: str = "development"
    condition: str = "direct"
    generation_status: Literal["failed", "succeeded"]
    execution_result: ExecutionResult | None = None
    passed: bool
    hashes: dict[str, str] = Field(min_length=1)


def _saved_file(root: Path, relative: str) -> Path:
    path = root / normalize_relative_path(relative)
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError(f"saved artifact escapes its run or is a symlink: {relative}")
    if not path.is_file():
        raise ValueError(f"saved artifact is missing: {relative}")
    return path


def _verify_hashes(run: Path, hashes: dict[str, str]) -> None:
    required = {
        "source.sas",
        "prompt.txt",
        "request.json",
        "policy.json",
        "input/input.csv",
        "expected/adjusted.csv",
    }
    if not required.issubset(hashes):
        raise ValueError("saved attempt lacks required input/policy hashes")
    for relative, expected in hashes.items():
        path = _saved_file(run, relative)
        if sha256_file(path) != validate_sha256(expected):
            raise ValueError(f"saved artifact hash mismatch: {relative}")


def reassess_local_model_suite(project_root: Path, suite_path: Path) -> tuple[bool, Path]:
    """Create a new linked report; never edit old reports or call a model or Docker."""
    root = project_root.resolve()
    runs = root / "reports" / "runs"
    original = suite_path if suite_path.is_absolute() else root / suite_path
    if not original.resolve().is_relative_to(runs.resolve()):
        raise ValueError("suite must be inside reports/runs")
    original = _saved_file(runs, original.relative_to(runs).as_posix())
    original_hash = sha256_file(original)
    suite = SavedSuite.model_validate_json(original.read_text(encoding="utf-8"))
    identities = [(attempt.model, attempt.case) for attempt in suite.attempts]
    expected_identities = {(model, case) for model in suite.models for case in suite.cases}
    if (
        len(suite.models) != len(set(suite.models))
        or len(suite.cases) != len(set(suite.cases))
        or len(identities) != len(set(identities))
        or set(identities) != expected_identities
    ):
        raise ValueError("suite must have exactly one attempt per model and case")
    report = runs / f"local-model-reassessment-{uuid4()}" / "report.json"
    report.parent.mkdir(parents=True)
    outcomes: list[dict[str, object]] = []
    for index, entry in enumerate(suite.attempts):
        outcome: dict[str, object] = {
            "model": entry.model,
            "case": entry.case,
            "previous_passed": entry.passed,
            "source_report": entry.report,
            "passed": False,
            "validation_status": "not_run",
            "comparison": None,
            "error": None,
        }
        try:
            source = _saved_file(root, entry.report)
            if not source.resolve().is_relative_to(runs.resolve()):
                raise ValueError("saved attempt must be inside reports/runs")
            source_hash = sha256_file(source)
            outcome["source_report_sha256"] = source_hash
            saved = SavedAttempt.model_validate_json(source.read_text(encoding="utf-8"))
            if (saved.model, saved.case, saved.passed) != (entry.model, entry.case, entry.passed):
                raise ValueError("suite identity/outcome differs from its saved attempt")
            fixture = select_cases(saved.case_set)[saved.case]
            _verify_hashes(source.parent, saved.hashes)
            outcome["condition"] = saved.condition
            outcome["case_set"] = saved.case_set
            outcome["verified_original_hashes"] = saved.hashes
            if (
                saved.generation_status == "succeeded"
                and saved.execution_result is not None
                and saved.execution_result.passed
            ):
                outcome["validation_status"] = "failed"
                if saved.execution_result.output_files != ["adjusted.csv"]:
                    raise ValueError("output contract requires exactly adjusted.csv")
                required = {"source/main.py", "response.json", "output/adjusted.csv"}
                if not required.issubset(saved.hashes):
                    raise ValueError("successful execution lacks candidate/response/output hashes")
                policy = numeric_policy(fixture)
                policy_path = report.parent / f"attempt-{index:04d}" / "policy.json"
                policy_path.parent.mkdir()
                policy_path.write_text(policy.to_json(), encoding="utf-8")
                outcome["policy"] = policy_path.relative_to(root).as_posix()
                outcome["policy_sha256"] = sha256_file(policy_path)
                comparison = compare_artifacts(
                    load_artifact(
                        _saved_file(source.parent, "output/adjusted.csv"), key=fixture.key
                    ),
                    load_artifact(
                        _saved_file(source.parent, "expected/adjusted.csv"), key=fixture.key
                    ),
                    artifact="SYNTHETIC_ADJUSTED",
                    policy=policy,
                )
                _verify_hashes(source.parent, saved.hashes)
                outcome["comparison"] = comparison.model_dump(mode="json")
                outcome["validation_status"] = "passed" if comparison.passed else "failed"
                outcome["passed"] = comparison.passed
            else:
                outcome["reason"] = "original generation or execution did not succeed; not rerun"
            if sha256_file(source) != source_hash:
                raise ValueError("saved report changed during reassessment")
        except (OSError, ValueError, KeyError) as error:
            outcome["passed"] = False
            outcome["validation_status"] = "failed"
            outcome["error"] = str(error)
        outcomes.append(outcome)
    if sha256_file(original) != original_hash:
        raise ValueError("saved suite changed during reassessment")
    passed = all(outcome["passed"] is True for outcome in outcomes)
    report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "scope": "host-only saved-output reassessment; no SAS-runtime parity",
                "validation_policy_version": VALIDATION_POLICY_VERSION,
                "reassessor_sha256": sha256_file(Path(__file__)),
                "validation_contract_sha256": sha256_file(
                    Path(__file__).with_name("local_model_validation.py")
                ),
                "source_suite": original.relative_to(root).as_posix(),
                "source_suite_sha256": original_hash,
                "models": suite.models,
                "cases": suite.cases,
                "generation_performed": False,
                "execution_performed": False,
                "human_review": "not_recorded",
                "attempts": outcomes,
                "passed": passed,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return passed, report
