"""Connect model-generation evidence to the existing Program 0 execution report."""

import json
from pathlib import Path

from sasguard.execution.program0 import CandidateReport
from sasguard.prototypes.program0_model import (
    ModelAttempt,
    ModelWorkflow,
    _candidate_code,
    _check_snapshot,
    _json_bytes,
    _repair_messages,
    _request,
    _Response,
    aggregate_diagnostics,
)
from sasguard.provenance.hashing import normalize_relative_path, sha256_file
from sasguard.reporting.models import RunReport
from sasguard.reporting.program0 import read_program0_report
from sasguard.reporting.reader import report_runs_directory, safe_file


def read_program0_model_report(root: Path, run: Path) -> RunReport:
    """Confirm candidate/response/execution links before attributing model generation."""
    workflow = ModelWorkflow.model_validate_json(safe_file(run, "workflow.json").read_bytes())
    if not workflow.attempts or not workflow.attempts[-1].execution_report:
        raise ValueError("No executed attempt; inspect workflow.json for generation failures.")
    last = workflow.attempts[-1]
    relative = normalize_relative_path(last.execution_report or "")
    execution_path = safe_file(root, relative)
    if execution_path.name != "report.json" or execution_path.parent.parent != (
        report_runs_directory(root)
    ):
        raise ValueError("model execution report must be in a top-level project run")
    report = read_program0_report(root, execution_path.parent)
    issues = list(report.evidence_issues)
    hashes = dict(report.evidence_hashes)
    hashes["workflow.json"] = sha256_file(run / "workflow.json", normalize_text=False)
    try:
        _check_snapshot(root, workflow)
        messages = json.loads(
            safe_file(root, workflow.preview_directory + "/messages.json").read_bytes()
        )
        if len(workflow.attempts) > workflow.settings.repair_attempts + 1:
            raise ValueError("attempt limit exceeded")
        for index, attempt in enumerate(workflow.attempts):
            directory = run / f"attempt-{index}"
            record = safe_file(run, f"attempt-{index}/attempt.json")
            if attempt.index != index or ModelAttempt.model_validate_json(record.read_bytes()) != (
                attempt
            ):
                raise ValueError("attempt records disagree")
            if index and attempt.parent_attempt_sha256 != sha256_file(
                safe_file(run / f"attempt-{index - 1}", "attempt.json"), normalize_text=False
            ):
                raise ValueError("parent attempt changed")
            for name in ("request.json", "response.json", "candidate.py"):
                digest = sha256_file(
                    safe_file(run, f"attempt-{index}/{name}"), normalize_text=False
                )
                if digest != attempt.hashes_bytes.get(name):
                    raise ValueError("generation evidence changed")
                hashes[f"attempt-{index}/{name}"] = digest
            response = _Response.model_validate_json(
                safe_file(directory, "response.json").read_bytes()
            )
            code = _candidate_code(response, workflow.settings.model)
            if code.encode() != safe_file(directory, "candidate.py").read_bytes():
                raise ValueError("candidate differs from model response")
            request = json.loads(safe_file(directory, "request.json").read_bytes())
            if request != _request(messages, workflow.settings):
                raise ValueError("request differs from recorded settings and feedback")
            if index < len(workflow.attempts) - 1:
                diagnostic_file = safe_file(directory, "repair-diagnostics.json")
                if attempt.hashes_bytes.get("repair-diagnostics.json") != sha256_file(
                    diagnostic_file, normalize_text=False
                ):
                    raise ValueError("diagnostic changed")
                previous_execution = safe_file(root, attempt.execution_report or "")
                if sha256_file(previous_execution, normalize_text=False) != (
                    attempt.execution_report_sha256
                ):
                    raise ValueError("parent execution changed")
                previous_report = CandidateReport.model_validate_json(
                    previous_execution.read_bytes()
                )
                diagnostics = _json_bytes(aggregate_diagnostics(previous_report))
                if diagnostic_file.read_bytes() != diagnostics:
                    raise ValueError("repair feedback differs from automatic aggregates")
                messages.extend(_repair_messages(code, diagnostics))
        candidate = safe_file(execution_path.parent, "source/main.py")
        if (
            last.generation_status != "completed"
            or last.execution_report_sha256 != sha256_file(execution_path, normalize_text=False)
            or last.hashes_bytes["candidate.py"] != sha256_file(candidate, normalize_text=False)
            or workflow.input_format.value != report.input_format
            or last.execution_status != report.execution_status
            or last.validation_status != report.validation_outcome
            or (workflow.status == "passed" and report.validation_status != "passed")
        ):
            raise ValueError("model and execution evidence disagree")
    except (OSError, ValueError, KeyError):
        issues.append("model_generation_evidence_not_confirmed")
    matched = "model_generation_evidence_not_confirmed" not in issues
    return report.model_copy(
        update={
            "code_origin": "model_generated" if matched else "not_recorded",
            "generation_status": "succeeded" if matched else "not_recorded",
            "model_name": workflow.settings.model if matched else None,
            "repair_attempts": len(workflow.attempts) - 1 if matched else None,
            "evidence_integrity": "not_confirmed" if issues else "matched",
            "evidence_issues": tuple(sorted(set(issues))),
            "evidence_hashes": hashes,
            "limitations": (
                "Only Program 0 on the supplied July 2025 release is evaluated.",
                "Model origin is linked through request, response, code, and execution hashes.",
                "Repair feedback is automatic aggregate diagnostics, without human repair hints.",
                "These local records are not a signed provider attestation or a new execution.",
                "Program 1, Program 2, eligibility, clustering, and ratings are not verified.",
            ),
        }
    )
