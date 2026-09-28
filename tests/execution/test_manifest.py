"""Tests for reproducible SASGuard run manifests."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from sasguard.execution.manifest import RunManifest, TokenUsage
from sasguard.execution.result import ExecutionResult, ExecutionStatus
from sasguard.provenance.hashing import hash_files, sha256_file
from sasguard.verification.artifact import ArtifactComparison, ReferenceSource


def comparison() -> ArtifactComparison:
    """Return a reusable passing artifact result."""
    return ArtifactComparison(
        artifact="STAR_2025JUL",
        passed=True,
        reference_source=ReferenceSource.SAS7BDAT,
        expected_rows=4566,
        actual_rows=4566,
        expected_columns=["PROVIDER_ID", "star"],
        actual_columns=["PROVIDER_ID", "star"],
        exact_cells=9132,
    )


def test_hash_files_is_path_sorted_and_deterministic(tmp_path: Path) -> None:
    (tmp_path / "source.sas").write_text("proc means; run;\n", encoding="utf-8")
    (tmp_path / "input.csv").write_text("id,value\n1,2\n", encoding="utf-8")

    hashes = hash_files(tmp_path, ["source.sas", "input.csv", "source.sas"])

    assert list(hashes) == ["input.csv", "source.sas"]
    assert hashes["source.sas"] == sha256_file(tmp_path / "source.sas")
    assert hashes == hash_files(tmp_path, ["input.csv", "source.sas"])


def test_text_hashes_are_portable_across_line_endings(tmp_path: Path) -> None:
    text_path = tmp_path / "source.sas"
    text_path.write_bytes(b"abcd\r\nrun;\r\n")
    windows_hash = sha256_file(text_path, chunk_size=5)

    text_path.write_bytes(b"abcd\nrun;\n")
    unix_hash = sha256_file(text_path, chunk_size=5)

    assert windows_hash == unix_hash


def test_binary_hashes_preserve_line_ending_bytes(tmp_path: Path) -> None:
    binary_path = tmp_path / "input.sas7bdat"
    binary_path.write_bytes(b"abcd\r\n")
    windows_hash = sha256_file(binary_path)

    binary_path.write_bytes(b"abcd\n")
    unix_hash = sha256_file(binary_path)

    assert windows_hash != unix_hash


def test_run_manifest_serializes_deterministically() -> None:
    result = comparison()
    manifest = RunManifest(
        run_id=UUID("12345678-1234-5678-1234-567812345678"),
        timestamp=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
        source_hashes={"source.sas": "a" * 64},
        input_hashes={"input.csv": "b" * 64},
        generated_code_hashes={"generated/program.py": "c" * 64},
        model="example-model",
        temperature=0,
        prompt_version="v1",
        token_usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        estimated_cost_usd=0.01,
        repair_attempts=1,
        runtime_seconds=2.5,
        reference_sources={"STAR_2025JUL": ReferenceSource.SAS7BDAT},
        artifact_results={"STAR_2025JUL": result},
    )

    first = manifest.to_json()
    second = manifest.to_json()
    payload = json.loads(first)

    assert first == second
    assert payload["schema_version"] == 1
    assert payload["model"] == "example-model"
    assert "model_name" not in payload
    assert payload["artifact_results"]["STAR_2025JUL"]["passed"] is True
    assert "api_key" not in first.lower()


def test_create_supplies_uuid_and_timezone_aware_timestamp() -> None:
    manifest = RunManifest.create(
        source_hashes={"source.sas": "a" * 64},
        input_hashes={"input.csv": "b" * 64},
    )

    assert isinstance(manifest.run_id, UUID)
    assert manifest.timestamp.utcoffset() == UTC.utcoffset(None)


def test_manifest_can_attach_an_isolated_execution_result() -> None:
    manifest = RunManifest.create(
        source_hashes={"source.sas": "a" * 64},
        input_hashes={"input.csv": "b" * 64},
    )
    execution = ExecutionResult(
        execution_id=UUID("12345678-1234-5678-1234-567812345678"),
        status=ExecutionStatus.SUCCEEDED,
        exit_code=0,
        runtime_seconds=1.5,
        output_files=["result.csv"],
    )

    updated = manifest.with_execution_result(execution)

    assert updated.execution_result == execution
    assert updated.runtime_seconds == 1.5
    assert json.loads(updated.to_json())["execution_result"]["status"] == "succeeded"


def test_manifest_rejects_partial_translation_metadata() -> None:
    with pytest.raises(ValidationError, match="recorded together"):
        RunManifest(
            run_id=UUID("12345678-1234-5678-1234-567812345678"),
            timestamp=datetime.now(UTC),
            source_hashes={"source.sas": "a" * 64},
            input_hashes={"input.csv": "b" * 64},
            model="example-model",
        )


def test_manifest_rejects_naive_timestamp_and_bad_hash() -> None:
    base = {
        "run_id": UUID("12345678-1234-5678-1234-567812345678"),
        "source_hashes": {"source.sas": "a" * 64},
        "input_hashes": {"input.csv": "b" * 64},
    }

    with pytest.raises(ValidationError, match="timezone"):
        RunManifest(timestamp=datetime(2026, 9, 9, 12, 0), **base)

    with pytest.raises(ValidationError, match="64 hexadecimal"):
        RunManifest(
            timestamp=datetime.now(UTC),
            **{**base, "input_hashes": {"input.csv": "not-a-hash"}},
        )


def test_manifest_rejects_artifact_key_or_reference_conflicts() -> None:
    result = comparison()
    base = {
        "run_id": UUID("12345678-1234-5678-1234-567812345678"),
        "timestamp": datetime.now(UTC),
        "source_hashes": {"source.sas": "a" * 64},
        "input_hashes": {"input.csv": "b" * 64},
    }

    with pytest.raises(ValidationError, match="does not match"):
        RunManifest(
            **base,
            artifact_results={"WRONG_NAME": result},
        )

    with pytest.raises(ValidationError, match="conflicts"):
        RunManifest(
            **base,
            reference_sources={"STAR_2025JUL": ReferenceSource.CSV},
            artifact_results={"STAR_2025JUL": result},
        )
