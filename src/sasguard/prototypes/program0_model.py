"""Record bounded Program 0 model attempts, isolated execution, and host validation."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from http.client import HTTPSConnection
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from sasguard.execution.program0 import (
    VALIDATION_SOURCE_PATHS,
    CandidateInputFormat,
    CandidateReport,
    CandidateStatus,
    run_program0_candidate,
    validate_collected_program0,
)
from sasguard.execution.runner import RunnerLimits
from sasguard.prototypes.local_model import GeneratedPython
from sasguard.prototypes.program0_feedback import structural_feedback
from sasguard.prototypes.program0_prompt import (
    PromptPreviewRecord,
    _selected_file,
    check_program0_prompt,
)
from sasguard.provenance.hashing import hash_files, sha256_file
from sasguard.verification.integrity import load_and_verify_integrity

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ModelSettings(BaseModel):
    """Explicit model settings with bounded requests and no transport retries."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    model: str = Field(default="gpt-6-luna", min_length=1, max_length=128)
    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    max_output_tokens: int = Field(default=8192, ge=128, le=32768)
    repair_attempts: int = Field(default=0, ge=0, le=2)
    api_timeout_seconds: float = Field(default=180, gt=0, le=300)


class ModelAttempt(BaseModel):
    """Generation success, execution success, and parity are independent outcomes."""

    model_config = ConfigDict(extra="forbid")
    index: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    condition: Literal["direct", "repair_with_automatic_aggregate_diagnostics"]
    generation_status: Literal["submitted", "completed", "failed"] = "submitted"
    execution_status: str = "not_run"
    collection_status: str = "not_run"
    validation_status: str = "not_run"
    response_model: str | None = None
    usage: dict[str, JsonValue] | None = None
    http_status: int | None = None
    hashes_bytes: dict[str, str] = Field(default_factory=dict)
    parent_attempt_sha256: str | None = None
    execution_report: str | None = None
    execution_report_sha256: str | None = None
    error: str | None = None
    human_review: Literal["not_recorded"] = "not_recorded"


class ModelWorkflow(BaseModel):
    """Local evidence for a Program 0 experiment, never a full pipeline verdict."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    kind: Literal["program0_model_workflow"] = "program0_model_workflow"
    scope: Literal["Program 0 only; CMS July 2025"] = "Program 0 only; CMS July 2025"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    code_origin: Literal["model_generated"] = "model_generated"
    settings: ModelSettings
    input_format: CandidateInputFormat
    preview_directory: str
    preview_sha256_bytes: str
    messages_sha256_bytes: str
    project_hashes_lf: dict[str, str]
    controller_hashes_lf: dict[str, str]
    image: str
    diagnostic_version: Literal["program0-aggregate-v1", "program0-aggregate-v2"] = (
        "program0-aggregate-v1"
    )
    status: Literal["running", "passed", "failed", "error"] = "running"
    attempts: list[ModelAttempt] = Field(default_factory=list)
    human_review: Literal["not_recorded"] = "not_recorded"
    full_pipeline_verified: Literal[False] = False
    estimated_cost_usd: None = None
    limitations: tuple[str, ...] = (
        "Only Program 0 on the supplied July 2025 release is evaluated.",
        "Automatic repair receives aggregate diagnostics; no human repair hints are added.",
        "Usage is recorded as returned by the provider; dollar cost is not estimated.",
        "Human review and client release approval are not established by this command.",
    )


class _Response(BaseModel):
    status: str
    model: str
    output: list[dict[str, JsonValue]]
    usage: dict[str, JsonValue] | None = None


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _save(path: Path, model: BaseModel) -> None:
    # Replace the record atomically, so interruption leaves the preceding valid record.
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(_json_bytes(model.model_dump(mode="json")))
    temporary.replace(path)


def _submit_request(body: bytes, key: str, timeout: float) -> tuple[int, bytes]:
    connection = HTTPSConnection("api.openai.com", timeout=timeout)
    try:
        connection.request(
            "POST",
            "/v1/responses",
            body=body,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        return response.status, data
    finally:
        connection.close()


def aggregate_diagnostics(report: CandidateReport) -> dict[str, JsonValue]:
    """Allowlist aggregate feedback; omit keys, row values, stdout, and exception text."""
    artifacts: dict[str, JsonValue] = {}
    for filename, comparison in report.validation_results.items():
        artifacts[filename] = {
            "passed": comparison.passed,
            "expected_rows": comparison.expected_rows,
            "actual_rows": comparison.actual_rows,
            "expected_columns": cast(JsonValue, comparison.expected_columns),
            "missing_columns": cast(JsonValue, comparison.missing_columns),
            "mismatched_columns": cast(JsonValue, comparison.mismatched_columns),
            "missing_key_count": len(comparison.missing_keys),
            "extra_key_count": len(comparison.extra_keys),
            "mismatched_cells": comparison.mismatched_cells,
            "missingness_mismatches": comparison.missingness_mismatches,
        }
    return {
        "origin": "automatic_aggregate_diagnostics",
        "collection_status": report.status.value,
        "validation_status": report.validation_status,
        "missing_outputs": cast(JsonValue, report.missing_outputs),
        # Raw errors can contain row values. Only the affected filenames are disclosed.
        "malformed_outputs": cast(JsonValue, sorted(report.malformed_outputs)),
        "validation_error_files": cast(JsonValue, sorted(report.validation_errors)),
        "artifacts": artifacts,
    }


def _request(messages: list[dict[str, str]], settings: ModelSettings) -> dict[str, JsonValue]:
    return {
        "model": settings.model,
        "reasoning": {"effort": settings.reasoning_effort},
        "max_output_tokens": settings.max_output_tokens,
        "store": False,
        "service_tier": "default",
        "input": cast(JsonValue, messages),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "generated_python",
                "strict": True,
                "schema": cast(JsonValue, GeneratedPython.model_json_schema()),
            }
        },
    }


def repair_diagnostics(
    project_root: Path, report: CandidateReport, execution_report: Path, version: str
) -> dict[str, JsonValue]:
    """Retain legacy feedback reconstruction while adding versioned structural facts."""
    feedback = aggregate_diagnostics(report)
    if version == "program0-aggregate-v2":
        feedback.update(
            structural_feedback(project_root, execution_report.parent / "output", report)
        )
    elif version != "program0-aggregate-v1":
        raise ValueError("unsupported repair diagnostic version")
    return feedback


def _candidate_code(response: _Response, requested_model: str) -> str:
    if response.status != "completed" or response.model != requested_model:
        raise ValueError("generation_incomplete_or_model_changed")
    texts = []
    for item in response.output:
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            raise ValueError("malformed_model_message")
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                raise ValueError("model_refusal_or_unsupported_content")
            if not isinstance(part.get("text"), str):
                raise ValueError("malformed_model_text")
            texts.append(cast(str, part["text"]))
    if len(texts) != 1:
        raise ValueError("expected_one_code_response")
    return GeneratedPython.model_validate_json(texts[0]).code


def _repair_messages(code: str, diagnostics: bytes) -> list[dict[str, str]]:
    return [
        {"role": "assistant", "content": json.dumps({"code": code})},
        {
            "role": "user",
            "content": (
                "Repair the preceding code using the supplied SAS and runtime contract. "
                "Return the complete standalone program in the same JSON code format. "
                "The following host-generated aggregate diagnostics contain no reference rows. "
                "Do not claim verification or change the validation rules.\n" + diagnostics.decode()
            ),
        },
    ]


def _check_snapshot(root: Path, workflow: ModelWorkflow) -> None:
    expected = workflow.project_hashes_lf | workflow.controller_hashes_lf
    if hash_files(root, expected) != expected:
        raise ValueError("source_input_or_controller_changed")
    if not load_and_verify_integrity(root, root / "configs/protected-artifacts.json").passed:
        raise ValueError("protected_artifact_integrity_failed")
    check = check_program0_prompt(root, Path(workflow.preview_directory))
    preview = root / workflow.preview_directory / "preview.json"
    if (
        check.status != "matched"
        or check.messages_sha256 != workflow.messages_sha256_bytes
        or sha256_file(preview, normalize_text=False) != workflow.preview_sha256_bytes
    ):
        raise ValueError("prompt_snapshot_changed")


def _write_summary(run: Path, workflow: ModelWorkflow) -> None:
    lines = [
        "# Program 0 model experiment",
        "",
        f"Scope: {workflow.scope}. Overall status: {workflow.status}.",
        f"Model: {workflow.settings.model}. Reasoning: {workflow.settings.reasoning_effort}.",
        "",
        "| Attempt | Condition | Generation | Execution | SAS comparison |",
        "|---|---|---|---|---|",
    ]
    for attempt in workflow.attempts:
        lines.append(
            f"| {attempt.index} | {attempt.condition} | {attempt.generation_status} | "
            f"{attempt.execution_status} | {attempt.validation_status} |"
        )
    lines.extend(["", *workflow.limitations, "", "See workflow.json and attempt-*/attempt.json."])
    (run / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_program0_model(
    project_root: Path,
    preview_directory: Path,
    *,
    image: str,
    settings: ModelSettings | None = None,
    limits: RunnerLimits | None = None,
) -> tuple[ModelWorkflow, Path]:
    """Submit a checked prompt and evaluate unchanged model code only inside Docker.

    Invoking this function authorizes the source/header payload and at most 1 +
    repair_attempts API calls. Read the key from SASGUARD_API_KEY on the host only.
    Existing previews and attempts are never rewritten. Infrastructure and integrity
    failures stop the workflow rather than consuming repair requests.
    """
    root = project_root.resolve()
    settings = settings or ModelSettings()
    key = os.environ.get("SASGUARD_API_KEY", "").strip()
    if len(key) < 16:
        raise ValueError("Set SASGUARD_API_KEY in the controller environment.")
    preview_directory = (
        preview_directory if preview_directory.is_absolute() else root / preview_directory
    ).resolve()
    check = check_program0_prompt(root, preview_directory)
    if check.status != "matched":
        raise ValueError("Prompt preview changed; prepare and review a fresh preview.")
    preview = PromptPreviewRecord.model_validate_json(
        _selected_file(preview_directory, "preview.json").read_bytes()
    )
    messages: list[dict[str, str]] = json.loads(
        _selected_file(preview_directory, "messages.json").read_bytes()
    )
    workflow = ModelWorkflow(
        settings=settings,
        input_format=CandidateInputFormat(preview.input_format.value),
        preview_directory=preview_directory.relative_to(root).as_posix(),
        preview_sha256_bytes=sha256_file(preview_directory / "preview.json", normalize_text=False),
        messages_sha256_bytes=check.messages_sha256,
        project_hashes_lf=preview.source_hashes_lf | preview.input_hashes_lf,
        controller_hashes_lf=hash_files(
            root,
            [
                *VALIDATION_SOURCE_PATHS,
                "src/sasguard/execution/program0.py",
                "src/sasguard/prototypes/program0_prompt.py",
                "src/sasguard/prototypes/program0_model.py",
                "src/sasguard/prototypes/program0_feedback.py",
                "src/sasguard/prototypes/local_model.py",
            ],
        ),
        image=image,
        diagnostic_version="program0-aggregate-v2",
    )
    _check_snapshot(root, workflow)
    run = root / "reports/runs" / f"program0-model-{uuid4()}"
    run.mkdir()
    _save(run / "workflow.json", workflow)
    for index in range(settings.repair_attempts + 1):
        directory = run / f"attempt-{index}"
        directory.mkdir()
        attempt = ModelAttempt(
            index=index,
            condition="direct" if index == 0 else "repair_with_automatic_aggregate_diagnostics",
            parent_attempt_sha256=(
                sha256_file(run / f"attempt-{index - 1}" / "attempt.json", normalize_text=False)
                if index
                else None
            ),
        )
        workflow.attempts.append(attempt)
        _save(directory / "attempt.json", attempt)
        _save(run / "workflow.json", workflow)
        try:
            _check_snapshot(root, workflow)
            request = _json_bytes(_request(messages, settings))
            if key.encode() in request:
                raise ValueError("credential_in_request_payload")
            (directory / "request.json").write_bytes(request)
            attempt.hashes_bytes["request.json"] = hashlib.sha256(request).hexdigest()
            _save(directory / "attempt.json", attempt)
            status, body = _submit_request(request, key, settings.api_timeout_seconds)
            attempt.http_status = status
            if key.encode() in body:
                raise ValueError("credential_in_response")
            (directory / "response.json").write_bytes(body)
            attempt.hashes_bytes["response.json"] = hashlib.sha256(body).hexdigest()
            if status != 200:
                raise ValueError("provider_http_error")
            response = _Response.model_validate_json(body)
            attempt.response_model = response.model
            attempt.usage = response.usage
            code = _candidate_code(response, settings.model)
            candidate = directory / "candidate.py"
            candidate.write_bytes(code.encode())
            attempt.hashes_bytes["candidate.py"] = sha256_file(candidate, normalize_text=False)
            attempt.generation_status = "completed"
            _save(directory / "attempt.json", attempt)
            _check_snapshot(root, workflow)
            result, report_path = run_program0_candidate(
                root,
                candidate,
                image=image,
                limits=limits,
                input_format=workflow.input_format,
                validator=validate_collected_program0,
            )
            attempt.execution_status = (
                result.execution_result.status.value if result.execution_result else "not_run"
            )
            attempt.collection_status = result.status.value
            attempt.validation_status = result.validation_status
            attempt.execution_report = report_path.relative_to(root).as_posix()
            attempt.execution_report_sha256 = sha256_file(report_path, normalize_text=False)
            if sha256_file(candidate, normalize_text=False) != attempt.hashes_bytes["candidate.py"]:
                raise ValueError("generated_candidate_changed")
            _check_snapshot(root, workflow)
            if result.validation_status == "passed":
                workflow.status = "passed"
                break
            workflow.status = "failed"
            if (
                index == settings.repair_attempts
                or result.validation_status in ("validator_error", "hash_mismatch")
                or result.status
                in (
                    CandidateStatus.INTEGRITY_FAILED,
                    CandidateStatus.RUNNER_ERROR,
                    CandidateStatus.POLICY_VIOLATION,
                )
            ):
                break
            diagnostics = _json_bytes(
                repair_diagnostics(root, result, report_path, workflow.diagnostic_version)
            )
            (directory / "repair-diagnostics.json").write_bytes(diagnostics)
            attempt.hashes_bytes["repair-diagnostics.json"] = hashlib.sha256(
                diagnostics
            ).hexdigest()
            messages.extend(_repair_messages(code, diagnostics))
        except Exception as error:
            # Provider/network exceptions can echo headers. Never persist their text.
            attempt.error = (
                str(error)
                if type(error) is ValueError
                and str(error)
                in {
                    "credential_in_request_payload",
                    "credential_in_response",
                    "provider_http_error",
                    "generated_candidate_changed",
                    "generation_incomplete_or_model_changed",
                    "source_input_or_controller_changed",
                    "protected_artifact_integrity_failed",
                    "prompt_snapshot_changed",
                    "response_too_large",
                }
                else "controller_or_generation_error"
            )
            if attempt.generation_status != "completed":
                attempt.generation_status = "failed"
            workflow.status = "error"
            break
        finally:
            _save(directory / "attempt.json", attempt)
            _save(run / "workflow.json", workflow)
            _write_summary(run, workflow)
    return workflow, run / "workflow.json"
