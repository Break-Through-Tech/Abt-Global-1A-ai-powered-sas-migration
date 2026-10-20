"""Local Ollama smoke experiment using synthetic SAS and an isolated Docker runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from sasguard import compatibility
from sasguard.data import load_artifact
from sasguard.execution.environment import collect_python_environment
from sasguard.execution.runner import DockerExecutionRunner
from sasguard.prototypes.local_model_validation import (
    VALIDATION_POLICY_VERSION,
    numeric_policy,
    select_cases,
)
from sasguard.provenance.hashing import sha256_file, validate_sha256
from sasguard.verification import compare_artifacts

SYSTEM_PROMPT = (
    "Translate the supplied synthetic SAS into a complete Python entry point. "
    "Return exactly one JSON object with a code string. Do not include Markdown or explanations."
)
HELPER_VERSION = "sas-helpers-v2"
HELPER_GUIDANCE = """
Optional tested helpers are available in a read-only module next to your entry point.
Import them with: from sas_helpers import read_sas_csv, sas_lt, sas_sum
- read_sas_csv(path, key=None) returns a pandas DataFrame with uppercase column names.
  PROVIDER_ID is protected as text by default. For another textual key, specify key.
  The key preserves leading zeros and literal NA/NULL. Empty numeric fields are missing.
- sas_lt(series, finite_scalar) returns booleans for SAS numeric '<'. Ordinary numeric
  missing is below every finite number. Special SAS missing values are not supported.
- sas_sum(dataframe) performs row-wise SAS SUM for two or more numeric columns. It
  ignores missing arguments but returns missing if all arguments are missing.
  Ordinary arithmetic '+' still propagates missing; it is not this SUM function.
You may use these helpers or ordinary pandas as appropriate. Import every module you use.
Use os.environ and pathlib.Path for the declared input and output directories.
The helper module does not create outputs or perform validation for you.
"""


class GeneratedPython(BaseModel):
    """The model may propose code, but cannot provide its own test outcome."""

    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(min_length=1)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _request_json(
    endpoint: str, payload: dict[str, JsonValue] | None = None
) -> dict[str, JsonValue]:
    """Call only the local Ollama server, without proxies or redirect handling."""
    connection = HTTPConnection("127.0.0.1", 11434, timeout=300 if endpoint == "/api/chat" else 30)
    try:
        connection.request(
            "GET" if payload is None else "POST",
            endpoint,
            body=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise ValueError(f"local Ollama {endpoint} returned HTTP {response.status}")
        decoded: object = json.loads(body)
        if not isinstance(decoded, dict):
            raise ValueError("local Ollama response must be a JSON object")
        return cast(dict[str, JsonValue], decoded)
    finally:
        connection.close()


def _installed_model(model: str) -> dict[str, JsonValue]:
    models = _request_json("/api/tags").get("models")
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict) and item.get("name") == model:
                digest = item.get("digest")
                if not isinstance(digest, str):
                    raise ValueError("installed model has no digest")
                validate_sha256(digest)
                definition = _request_json("/api/show", {"model": model})
                if (
                    item.get("remote_host")
                    or item.get("remote_model")
                    or definition.get("remote_host")
                    or definition.get("remote_model")
                    or model.endswith("-cloud")
                ):
                    raise ValueError("this experiment requires a downloaded local model")
                return {**item, "definition": definition}
    raise ValueError(f"model {model!r} is not installed; no model was downloaded")


def _candidate_code(response: dict[str, JsonValue], model: str) -> str:
    if response.get("model") != model:
        raise ValueError("response model differs from the requested model")
    if response.get("done") is not True or response.get("done_reason") != "stop":
        raise ValueError("generation did not finish normally; truncated code will not run")
    message = response.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError("generation has no message content")
    candidate = GeneratedPython.model_validate_json(content)
    return candidate.code


def run_local_model_smoke(
    project_root: Path,
    *,
    model: str = "qwen3:4b",
    image: str = "sasguard-runner:local",
    case: str = "double-score",
    with_sas_helpers: bool = False,
    case_set: str = "development",
) -> tuple[bool, Path]:
    """Record one model attempt, run it in Docker, and check synthetic arithmetic.

    The model receives no supplied project material, actual input rows, or oracle values.
    Failed attempts remain in their own run directories. This is not the Program 0 baseline.
    """
    cases = select_cases(case_set)
    if case not in cases:
        raise ValueError(f"unknown synthetic case {case!r}; choose from {', '.join(cases)}")
    fixture = cases[case]
    prompt = fixture.prompt + (HELPER_GUIDANCE if with_sas_helpers else "")
    root = project_root.resolve()
    run = root / "reports" / "runs" / f"local-model-smoke-{uuid4()}"
    source, inputs, expected, output = (
        run / name for name in ("source", "input", "expected", "output")
    )
    for directory in (source, inputs, expected, output):
        directory.mkdir(parents=True)
    (run / "source.sas").write_text(fixture.sas_source, encoding="utf-8")
    (run / "prompt.txt").write_text(prompt, encoding="utf-8")
    (inputs / "input.csv").write_text(fixture.input_csv, encoding="utf-8")
    (expected / "adjusted.csv").write_text(fixture.expected_csv, encoding="utf-8")
    policy = numeric_policy(fixture)
    (run / "policy.json").write_text(policy.to_json(), encoding="utf-8")
    request: dict[str, JsonValue] = {
        "model": model,
        "stream": False,
        "think": False,
        "format": GeneratedPython.model_json_schema(),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 1200},
    }
    _write_json(run / "request.json", request)
    hashes = {
        path.relative_to(run).as_posix(): sha256_file(path)
        for path in (
            run / "source.sas",
            run / "prompt.txt",
            run / "request.json",
            run / "policy.json",
            inputs / "input.csv",
            expected / "adjusted.csv",
        )
    }
    if with_sas_helpers:
        helper_path = source / "sas_helpers.py"
        helper_path.write_bytes(Path(compatibility.__file__).read_bytes())
        hashes["source/sas_helpers.py"] = sha256_file(helper_path)
    report: dict[str, object] = {
        "schema_version": 1,
        "scope": "synthetic SAS smoke test; handwritten oracle; no SAS-runtime parity",
        "timestamp": datetime.now(UTC).isoformat(),
        "case": fixture.name,
        "case_set": case_set,
        "validation_policy_version": VALIDATION_POLICY_VERSION,
        "validation_contract_sha256": sha256_file(
            Path(__file__).with_name("local_model_validation.py")
        ),
        "prompt_version": fixture.prompt_version
        + (f"+{HELPER_VERSION}" if with_sas_helpers else ""),
        "condition": HELPER_VERSION if with_sas_helpers else "direct",
        "model": model,
        "generation_status": "failed",
        "execution_result": None,
        "validation_status": "not_run",
        "comparison": None,
        "human_review": "not_recorded",
        "hashes": hashes,
        "controller_sha256": sha256_file(Path(__file__)),
        "fixtures_sha256": sha256_file(
            Path(__file__).with_name(
                "local_model_cases.py" if case_set == "development" else "local_model_holdout.py"
            )
        ),
        "controller_environment": collect_python_environment().model_dump(mode="json"),
        "passed": False,
        "error": None,
    }
    try:
        metadata = _installed_model(model)
        report["model_metadata"] = metadata
        report["ollama_version"] = _request_json("/api/version")
        response = _request_json("/api/chat", request)
        _write_json(run / "response.json", response)
        hashes["response.json"] = sha256_file(run / "response.json")
        report["ollama_runtime"] = _request_json("/api/ps")
        if _installed_model(model)["digest"] != metadata["digest"]:
            raise ValueError("model digest changed during generation")
        code = _candidate_code(response, model)
        (source / "main.py").write_bytes(code.encode("utf-8"))
        hashes["source/main.py"] = sha256_file(source / "main.py")
        compile(code, "main.py", "exec")
        report["generation_status"] = "succeeded"
        execution = DockerExecutionRunner(image=image).run(
            source_directory=source,
            input_directory=inputs,
            output_directory=output,
            forbidden_host_paths=(root / "data", expected),
        )
        report["execution_result"] = execution.model_dump(mode="json")
        if execution.passed:
            report["validation_status"] = "failed"
            if execution.output_files != ["adjusted.csv"]:
                raise ValueError("output contract requires exactly adjusted.csv")
            hashes["output/adjusted.csv"] = sha256_file(output / "adjusted.csv")
            comparison = compare_artifacts(
                load_artifact(output / "adjusted.csv", key=fixture.key),
                load_artifact(expected / "adjusted.csv", key=fixture.key),
                artifact="SYNTHETIC_ADJUSTED",
                policy=policy,
            )
            report["comparison"] = comparison.model_dump(mode="json")
            report["validation_status"] = "passed" if comparison.passed else "failed"
            report["passed"] = comparison.passed
    except (OSError, ValueError, RuntimeError, SyntaxError, HTTPException) as error:
        report["error"] = str(error)
    report_path = run / "report.json"
    _write_json(report_path, report)
    return report["passed"] is True, report_path


def run_local_model_suite(
    project_root: Path,
    *,
    models: tuple[str, ...],
    image: str = "sasguard-runner:local",
    with_sas_helpers: bool = False,
    case_set: str = "development",
) -> tuple[bool, Path]:
    """Run each frozen synthetic case once per model and retain every attempt."""
    if not models or len(models) != len(set(models)):
        raise ValueError("choose at least one model, with no duplicate model tags")
    cases = select_cases(case_set)
    root = project_root.resolve()
    directory = root / "reports" / "runs" / f"local-model-suite-{uuid4()}"
    directory.mkdir(parents=True)
    path = directory / "report.json"
    attempts: list[dict[str, object]] = []
    suite: dict[str, object] = {
        "schema_version": 1,
        "scope": "synthetic documentation-based checks; no SAS-runtime parity",
        "timestamp": datetime.now(UTC).isoformat(),
        "models": list(models),
        "condition": HELPER_VERSION if with_sas_helpers else "direct",
        "cases": list(cases),
        "case_set": case_set,
        "validation_policy_version": VALIDATION_POLICY_VERSION,
        "attempts": attempts,
        "complete": False,
        "passed": False,
        "unload_errors": [],
    }
    _write_json(path, suite)
    unload_errors: list[str] = []
    for model in models:
        for case in cases:
            passed, report = run_local_model_smoke(
                root,
                model=model,
                image=image,
                case=case,
                with_sas_helpers=with_sas_helpers,
                case_set=case_set,
            )
            attempts.append(
                {
                    "model": model,
                    "case": case,
                    "passed": passed,
                    "report": report.relative_to(root).as_posix(),
                }
            )
            _write_json(path, suite)
        # Free the model just evaluated before measuring the next one on a small GPU.
        try:
            _request_json("/api/generate", {"model": model, "keep_alive": 0})
        except (OSError, ValueError, HTTPException) as error:
            unload_errors.append(f"{model}: {error}")
    suite["unload_errors"] = unload_errors
    suite["complete"] = True
    suite["passed"] = all(attempt["passed"] is True for attempt in attempts)
    _write_json(path, suite)
    return suite["passed"] is True, path
