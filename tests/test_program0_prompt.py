"""Preview payloads exclude hospital rows, oracle values, and reference Python."""

import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from sasguard import cli
from sasguard.execution.program0 import (
    INPUT_PATH,
    OUTPUT_FILENAMES,
    PROGRAM_PATH,
    program0_runtime_contract,
)
from sasguard.prototypes import program0_prompt
from sasguard.verification.integrity import build_integrity_manifest

ROW_SECRET = "PRIVATE_HOSPITAL_ROW_81073"
GOLD_SECRET = "TRUSTED_REFERENCE_VALUES_82913"
PYTHON_SECRET = "HUMAN_REFERENCE_CODE_75238"


def protect(root: Path) -> None:
    path = root / "configs/protected-artifacts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_integrity_manifest(root, ["data/Project_1"]).model_dump_json(), encoding="utf-8"
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    contents = {
        PROGRAM_PATH: '%include "Star_Macros.sas";\n%keep_hos(input, score, 1);\n',
        program0_prompt.MACRO_PATH: "%macro keep_hos(indsn,varlist,nmeasure);\n%mend;\n",
        INPUT_PATH: f"PROVIDER_ID,SCORE\n{ROW_SECRET},99\n",
        "data/Project_1/SAS Output CSV/LESS100_MEASURE.csv": GOLD_SECRET,
        "reference_python/program0.py": PYTHON_SECRET,
    }
    for relative, content in contents.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    protect(tmp_path)
    return tmp_path


def test_payload_reads_only_declared_inputs_and_never_calls_a_model(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read_paths = []
    original_open = Path.open
    allowed = {
        project / path
        for path in (
            PROGRAM_PATH,
            program0_prompt.MACRO_PATH,
            INPUT_PATH,
            "configs/protected-artifacts.json",
        )
    }

    def audited_open(path, mode="r", *args, **kwargs):
        if "r" in mode:
            assert path in allowed, f"unexpected prompt input: {path}"
            read_paths.append(path)
        return original_open(path, mode, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("a preview must not call a model, Docker, or the network")

    with monkeypatch.context() as audit:
        audit.setattr(Path, "open", audited_open)
        audit.setattr("sasguard.prototypes.local_model._request_json", forbidden)
        audit.setattr("sasguard.execution.runner.DockerExecutionRunner.run", forbidden)
        audit.setattr("socket.socket.connect", forbidden)
        audit.setattr(subprocess, "run", forbidden)
        directory = program0_prompt.preview_program0_prompt(project)
    assert set(read_paths) == allowed
    assert {path.name for path in directory.iterdir()} == {
        "messages.json",
        "prompt.txt",
        "contract.json",
        "preview.json",
    }
    messages = json.loads((directory / "messages.json").read_text(encoding="utf-8"))
    assert [item["role"] for item in messages] == ["system", "user"]
    payload = json.loads(messages[1]["content"])
    assert set(payload) == {"sas_sources", "runtime_contract"}
    assert [item["filename"] for item in payload["sas_sources"]] == [
        Path(PROGRAM_PATH).name,
        Path(program0_prompt.MACRO_PATH).name,
    ]
    assert payload["runtime_contract"] == program0_runtime_contract(["PROVIDER_ID", "SCORE"])
    assert payload["runtime_contract"]["output_filenames"] == list(OUTPUT_FILENAMES)
    for filename in ("messages.json", "prompt.txt", "contract.json", "preview.json"):
        text = (directory / filename).read_text(encoding="utf-8")
        for secret in (ROW_SECRET, GOLD_SECRET, PYTHON_SECRET, str(project)):
            assert secret not in text


def test_preview_is_deterministic_and_records_exact_payload_hashes(project: Path) -> None:
    first = program0_prompt.preview_program0_prompt(project)
    second = program0_prompt.preview_program0_prompt(project)
    assert first != second
    record = json.loads((first / "preview.json").read_text())
    for filename, digest in record["file_hashes_bytes"].items():
        content = (first / filename).read_bytes()
        assert hashlib.sha256(content).hexdigest() == digest
        assert content == (second / filename).read_bytes()
    assert record["messages_utf8_bytes"] == len((first / "messages.json").read_bytes())
    assert record["input_column_count"] == 2
    assert (
        record["generation_status"]
        == record["execution_status"]
        == record["validation_status"]
        == "not_run"
    )
    assert record["payload_approval"] == record["model_selection"] == "pending"
    assert record["human_review"] == "not_recorded"


@pytest.mark.parametrize("relative", [PROGRAM_PATH, program0_prompt.MACRO_PATH, INPUT_PATH])
def test_changed_protected_input_is_rejected_before_writing(project: Path, relative: str) -> None:
    (project / relative).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="protected baseline"):
        program0_prompt.preview_program0_prompt(project)
    assert not (project / "reports").exists()


@pytest.mark.parametrize("relative", [PROGRAM_PATH, program0_prompt.MACRO_PATH, INPUT_PATH])
def test_missing_selected_input_is_rejected(project: Path, relative: str) -> None:
    (project / relative).unlink()
    with pytest.raises(FileNotFoundError):
        program0_prompt.preview_program0_prompt(project)
    assert not (project / "reports").exists()


@pytest.mark.parametrize("relative", [PROGRAM_PATH, program0_prompt.MACRO_PATH, INPUT_PATH])
def test_reparse_inputs_are_rejected_before_reading(
    project: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    selected = project / relative
    original = Path.lstat

    def lstat(path: Path):
        metadata = original(path)
        if path == selected:
            return SimpleNamespace(st_mode=metadata.st_mode, st_file_attributes=0x400)
        return metadata

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(ValueError, match="reparse points"):
        program0_prompt.preview_program0_prompt(project)
    assert not (project / "reports").exists()


def test_changed_input_between_hash_and_header_read_is_rejected(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = program0_prompt.sha256_file
    calls = []

    def digest(path: Path) -> str:
        calls.append(path)
        return original(path) if len(calls) == 1 else "0" * 64

    monkeypatch.setattr(program0_prompt, "sha256_file", digest)
    with pytest.raises(ValueError, match="input changed"):
        program0_prompt.preview_program0_prompt(project)
    assert not (project / "reports").exists()


@pytest.mark.parametrize(
    "header",
    ["", "SCORE\n", "PROVIDER_ID,score,SCORE\n", "PROVIDER_ID,,SCORE\n", 'PROVIDER_ID,"unclosed\n'],
)
def test_malformed_schema_is_rejected(project: Path, header: str) -> None:
    (project / INPUT_PATH).write_text(header, encoding="utf-8")
    protect(project)
    with pytest.raises((ValueError, program0_prompt.csv.Error)):
        program0_prompt.preview_program0_prompt(project)
    assert not (project / "reports").exists()


def test_newlines_are_portable_and_no_previous_preview_is_overwritten(project: Path) -> None:
    first = program0_prompt.preview_program0_prompt(project)
    for relative in (PROGRAM_PATH, program0_prompt.MACRO_PATH):
        path = project / relative
        path.write_bytes(path.read_text().replace("\n", "\r\n").encode())
    second = program0_prompt.preview_program0_prompt(project)
    assert (first / "messages.json").read_bytes() == (second / "messages.json").read_bytes()
    before = {path.name: path.read_bytes() for path in first.iterdir()}
    with pytest.raises(FileExistsError):
        program0_prompt.preview_program0_prompt(project, output_directory=first)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == before


@pytest.mark.parametrize("relative", ["../outside", "reports/runs/nested/preview", "data/preview"])
def test_destination_must_be_a_direct_child_of_run_store(project: Path, relative: str) -> None:
    with pytest.raises(ValueError, match="direct child"):
        program0_prompt.preview_program0_prompt(project, output_directory=Path(relative))


def test_redirected_run_store_is_rejected(project: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside-prompt-store")
    link = project / "reports/runs"
    link.parent.mkdir()
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True
        )
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="inside the project"):
        program0_prompt.preview_program0_prompt(project)
    assert list(outside.iterdir()) == []


def test_cli_previews_without_model_options(project: Path) -> None:
    result = CliRunner().invoke(
        cli.app, ["preview-program0-prompt", "--project-root", str(project)]
    )
    assert result.exit_code == 0, result.output
    assert "No model call was made" in result.stdout
    result = CliRunner().invoke(cli.app, ["preview-program0-prompt", "--model", "test"])
    assert result.exit_code == 2


def test_cli_rejects_malformed_csv_without_traceback(project: Path) -> None:
    (project / INPUT_PATH).write_text('PROVIDER_ID,"unclosed\n', encoding="utf-8")
    protect(project)
    result = CliRunner().invoke(
        cli.app, ["preview-program0-prompt", "--project-root", str(project)]
    )
    assert result.exit_code == 2
    assert "could not be prepared" in result.output
    assert "Traceback" not in result.output


def test_saved_preview_check_is_read_only_and_offline(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = program0_prompt.preview_program0_prompt(project)
    before = {path: path.read_bytes() for path in directory.iterdir()}
    original = Path.open
    allowed = {
        *before,
        *(
            project / path
            for path in (
                PROGRAM_PATH,
                program0_prompt.MACRO_PATH,
                INPUT_PATH,
                "configs/protected-artifacts.json",
            )
        ),
    }

    def checked_open(path, mode="r", *args, **kwargs):
        assert "r" in mode and path in allowed
        return original(path, mode, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("checking a preview cannot call a model or Docker")

    with monkeypatch.context() as audit:
        audit.setattr(Path, "open", checked_open)
        audit.setattr("sasguard.prototypes.local_model._request_json", forbidden)
        audit.setattr("sasguard.execution.runner.DockerExecutionRunner.run", forbidden)
        audit.setattr("socket.socket.connect", forbidden)
        audit.setattr(subprocess, "run", forbidden)
        check = program0_prompt.check_program0_prompt(project, directory)
    assert check.status == "matched"
    assert check.issues == ()
    assert check.messages_sha256 == hashlib.sha256(before[directory / "messages.json"]).hexdigest()
    assert check.payload_approval == "pending"
    assert check.generation_status == "not_run"
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("name", ["messages.json", "prompt.txt", "contract.json"])
@pytest.mark.parametrize("rehash", [False, True])
def test_modified_payload_fails_even_if_its_recorded_hash_is_replaced(
    project: Path, name: str, rehash: bool
) -> None:
    directory = program0_prompt.preview_program0_prompt(project)
    path = directory / name
    path.write_bytes(path.read_bytes() + b"\nchanged\n")
    if rehash:
        record_path = directory / "preview.json"
        record = json.loads(record_path.read_text())
        record["file_hashes_bytes"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        record_path.write_text(json.dumps(record), encoding="utf-8")
    check = program0_prompt.check_program0_prompt(project, directory)
    assert check.status == "changed"
    assert f"{name}:differs_from_fixed_payload" in check.issues
    if not rehash:
        assert f"{name}:recorded_hash_changed" in check.issues


@pytest.mark.parametrize(
    "field,value,issue",
    [
        ("messages_utf8_bytes", 1, "message_byte_count_changed"),
        ("input_column_count", 1, "input_column_count_changed"),
        ("file_hashes_bytes", {}, "payload_hash_layout_changed"),
        ("source_hashes_lf", {}, "selected_snapshot_changed"),
        ("input_hashes_lf", {}, "selected_snapshot_changed"),
    ],
)
def test_inconsistent_record_cannot_pass_the_check(
    project: Path, field: str, value: object, issue: str
) -> None:
    directory = program0_prompt.preview_program0_prompt(project)
    path = directory / "preview.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    check = program0_prompt.check_program0_prompt(project, directory)
    assert check.status == "changed"
    assert issue in check.issues


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_version", "other-v99"),
        ("payload_approval", "approved"),
        ("generation_status", "succeeded"),
        ("human_review", "approved"),
        ("schema_version", 2),
        ("timestamp", "2026-10-22T12:00:00"),
        ("limitations", []),
        ("file_hashes_bytes", {"messages.json": "bad"}),
    ],
)
def test_unsupported_or_misleading_record_is_rejected(
    project: Path, field: str, value: object
) -> None:
    directory = program0_prompt.preview_program0_prompt(project)
    path = directory / "preview.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        program0_prompt.check_program0_prompt(project, directory)


def test_extra_file_is_flagged_without_reading_its_content(project: Path) -> None:
    directory = program0_prompt.preview_program0_prompt(project)
    (directory / "response.txt").write_text(ROW_SECRET, encoding="utf-8")
    check = program0_prompt.check_program0_prompt(project, directory)
    assert check.status == "changed"
    assert "preview_layout_changed" in check.issues
    assert ROW_SECRET not in check.model_dump_json()


@pytest.mark.parametrize("name", ["preview.json", "messages.json", "prompt.txt", "contract.json"])
def test_missing_preview_file_is_not_treated_as_a_match(project: Path, name: str) -> None:
    directory = program0_prompt.preview_program0_prompt(project)
    (directory / name).unlink()
    with pytest.raises(FileNotFoundError):
        program0_prompt.check_program0_prompt(project, directory)


def test_check_cli_distinguishes_match_change_and_invalid_input(project: Path) -> None:
    directory = program0_prompt.preview_program0_prompt(project)
    command = ["check-program0-prompt", str(directory), "--project-root", str(project)]
    result = CliRunner().invoke(cli.app, command)
    assert result.exit_code == 0, result.output
    assert "integrity: matched" in result.stdout
    assert "approval remains pending" in result.stdout
    (directory / "prompt.txt").write_text("changed", encoding="utf-8")
    result = CliRunner().invoke(cli.app, command)
    assert result.exit_code == 1
    assert "integrity: changed" in result.stdout
    result = CliRunner().invoke(cli.app, ["check-program0-prompt", str(project)])
    assert result.exit_code == 2
    assert "could not be checked" in result.output
    assert "Traceback" not in result.output
    result = CliRunner().invoke(
        cli.app,
        [
            "preview-program0-prompt",
            "--project-root",
            str(project),
            "--output-directory",
            "data/preview",
        ],
    )
    assert result.exit_code == 2


@pytest.fixture
def sas_input(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = (project / INPUT_PATH).with_suffix(".sas7bdat")
    binary.write_bytes(b"synthetic source input containing " + ROW_SECRET.encode())
    protect(project)

    def metadata_only(path, *, metadataonly):
        assert path == binary
        assert metadataonly is True
        return None, SimpleNamespace(column_names=["provider_id", "score"])

    monkeypatch.setattr(program0_prompt.pyreadstat, "read_sas7bdat", metadata_only)
    return binary


def test_sas_preview_uses_metadata_only_and_records_the_selected_source(
    project: Path, sas_input: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.open
    reads = []
    allowed = {
        sas_input,
        *(
            project / relative
            for relative in (
                PROGRAM_PATH,
                program0_prompt.MACRO_PATH,
                "configs/protected-artifacts.json",
            )
        ),
    }

    def audited_open(path, mode="r", *args, **kwargs):
        if "r" in mode:
            assert path in allowed
            reads.append(path)
        return original(path, mode, *args, **kwargs)

    with monkeypatch.context() as audit:
        audit.setattr(Path, "open", audited_open)
        directory = program0_prompt.preview_program0_prompt(
            project, input_format=program0_prompt.PromptInputFormat.SAS7BDAT
        )
    assert set(reads) == allowed
    record = json.loads((directory / "preview.json").read_text())
    assert record["input_format"] == "sas7bdat"
    assert set(record["input_hashes_lf"]) == {sas_input.relative_to(project).as_posix()}
    messages = json.loads((directory / "messages.json").read_text())
    contract = json.loads(messages[1]["content"])["runtime_contract"]
    assert contract["input_filename"] == "alldata_2025jul.csv"
    assert contract["input_columns"] == ["PROVIDER_ID", "SCORE"]
    assert contract == program0_runtime_contract(["PROVIDER_ID", "SCORE"])
    assert ROW_SECRET not in (directory / "messages.json").read_text()
    check = program0_prompt.check_program0_prompt(project, directory)
    assert check.status == "matched"
    assert check.input_format is program0_prompt.PromptInputFormat.SAS7BDAT
    record["input_format"] = "csv"
    (directory / "preview.json").write_text(json.dumps(record), encoding="utf-8")
    check = program0_prompt.check_program0_prompt(project, directory)
    assert check.status == "changed"
    assert "selected_snapshot_changed" in check.issues


def test_legacy_csv_preview_still_checks_without_an_input_format_field(project: Path) -> None:
    directory = program0_prompt.preview_program0_prompt(project)
    path = directory / "preview.json"
    record = json.loads(path.read_text())
    del record["input_format"]
    path.write_text(json.dumps(record), encoding="utf-8")
    check = program0_prompt.check_program0_prompt(project, directory)
    assert check.status == "matched"
    assert check.input_format is program0_prompt.PromptInputFormat.CSV


def test_cli_selects_sas_source_without_calling_a_model(project: Path, sas_input: Path) -> None:
    result = CliRunner().invoke(
        cli.app,
        ["preview-program0-prompt", "--project-root", str(project), "--input-format", "sas7bdat"],
    )
    assert result.exit_code == 0, result.output
    assert "Input source: sas7bdat" in result.stdout
    assert "No model call was made" in result.stdout


def test_unknown_input_format_is_rejected(project: Path) -> None:
    result = CliRunner().invoke(
        cli.app,
        ["preview-program0-prompt", "--project-root", str(project), "--input-format", "unknown"],
    )
    assert result.exit_code == 2
    assert not (project / "reports").exists()
