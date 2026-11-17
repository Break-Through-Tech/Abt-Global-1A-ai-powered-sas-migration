"""Replay the July 2025 hybrid chain with one recorded Program 2 correction."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from uuid import uuid4

from sasguard.execution.program0 import (
    CandidateInputFormat,
    run_program0_candidate,
    validate_collected_program0,
)
from sasguard.execution.runner import DockerExecutionRunner, RunnerLimits
from sasguard.prototypes.program01 import DOMAINS, run_program01_chain
from sasguard.prototypes.program2_model import _verified_chain_sources
from sasguard.provenance.hashing import sha256_file
from sasguard.reporting.reader import report_runs_directory, safe_file
from sasguard.verification.integrity import load_and_verify_integrity
from sasguard.verification.program2 import (
    ARTIFACTS,
    POLICY_PATH,
    check_domain_passthrough,
    validate_program2,
)

PROGRAM0_SHA256 = "5c03a29162659ee102cecaa0eb889e4cbeaf410d3638b5c161c8032668be822b"
PROGRAM2_SHA256 = "77418712e677a0793e1cde1d04d69339e89c8adf89a6968fc4fd101b9532c01f"
PROGRAM2_POLICY_SHA256 = "05af4a42413c5cedf3bad28a069530d0333f9b7599dc693a467629e3647e962f"
REPLACEMENTS = (
    (
        "STRICT controls whether an empty cluster's seed is replaced.",
        "STRICT excludes distant points from center updates.",
    ),
    (
        "            members = x[new_labels == cluster_id]\n",
        "            mask = new_labels == cluster_id\n"
        "            if strict:\n"
        "                mask &= nearest_distance <= 1\n"
        "            members = x[mask]\n",
    ),
    (
        "    labels, centers = fastclus_1d(x, first_centers, strict=True)\n",
        "    labels, centers = fastclus_1d(x, first_centers, strict=True)\n"
        "    labels = labels + 1\n"
        "    distances = np.abs(x - centers[labels - 1])\n"
        "    labels[distances > 1] *= -1\n",
    ),
    ("star_for_cluster[int(label)]", "star_for_cluster[abs(int(label)) - 1]"),
)


def replay(root: Path, program0: Path, program2: Path, image: str) -> int:
    integrity = root / "configs/protected-artifacts.json"
    for candidate, expected in ((program0, PROGRAM0_SHA256), (program2, PROGRAM2_SHA256)):
        if candidate.is_symlink() or sha256_file(candidate, normalize_text=False) != expected:
            raise ValueError("candidate bytes differ from the recorded November 10 experiment")
    if not load_and_verify_integrity(root, integrity).passed:
        raise ValueError("protected artifact integrity failed")
    if sha256_file(root / POLICY_PATH) != PROGRAM2_POLICY_SHA256:
        raise ValueError("Program 2 comparison policy differs from the recorded baseline")
    corrected = program2.read_bytes().decode("utf-8")
    for original, replacement in REPLACEMENTS:
        if corrected.count(original) != 1:
            raise ValueError("unexpected correction site in Program 2 candidate")
        corrected = corrected.replace(original, replacement, 1)

    limits = RunnerLimits(timeout_seconds=120)
    program0_result, program0_report = run_program0_candidate(
        root,
        program0,
        image=image,
        limits=limits,
        input_format=CandidateInputFormat.SAS7BDAT,
        validator=validate_collected_program0,
    )
    print(f"Program 0: {program0_result.validation_status}. {program0_report}")
    if program0_result.validation_status != "passed":
        return 1
    staged_program0 = safe_file(program0_report.parent, "source/main.py")
    if sha256_file(staged_program0, normalize_text=False) != PROGRAM0_SHA256:
        raise ValueError("Program 0 replay staged different candidate bytes")
    chain, chain_path = run_program01_chain(
        root, program0_report.parent, image=image, limits=limits
    )
    print(f"Program 1: {chain.status}. {chain_path}")
    if chain.status != "passed":
        return 1

    sources = _verified_chain_sources(root, chain_path.parent)
    run = report_runs_directory(root) / f"program2-strict-replay-{uuid4()}"
    source, inputs, output = (run / name for name in ("source", "input", "output"))
    source.mkdir(parents=True)
    inputs.mkdir()
    corrected_path = source / "main.py"
    corrected_path.write_bytes(corrected.encode("utf-8"))
    corrected_hash = sha256_file(corrected_path, normalize_text=False)
    input_hashes = {}
    for artifact, path in sources.items():
        target = inputs / f"{artifact.lower()}.csv"
        input_hashes[target.name] = sha256_file(path, normalize_text=False)
        shutil.copyfile(path, target)

    execution = DockerExecutionRunner(image=image, limits=limits).run(
        source_directory=source,
        input_directory=inputs,
        output_directory=output,
        forbidden_host_paths=(root / "data", root / "reference_python"),
    )
    (run / "execution.json").write_text(execution.to_json(), encoding="utf-8")
    verdict = "failed"
    passed_outputs = 0
    if execution.passed and set(execution.output_files) == set(ARTIFACTS):
        validation = validate_program2(root, output)
        try:
            validation.input_passthrough = check_domain_passthrough(inputs, output)
        except (OSError, ValueError, KeyError):
            validation.status = "malformed_outputs"
            validation.errors["input_passthrough"] = "not_comparable"
        else:
            if validation.status == "passed" and not validation.input_passthrough.passed:
                validation.status = "failed"
        (run / "validation.json").write_text(validation.model_dump_json(indent=2), encoding="utf-8")
        passed_outputs = sum(item.passed for item in validation.comparisons.values())
        if validation.status == "passed":
            verdict = "passed"
    evidence_intact = (
        sha256_file(corrected_path, normalize_text=False) == corrected_hash
        and sha256_file(root / POLICY_PATH) == PROGRAM2_POLICY_SHA256
        and sha256_file(program2, normalize_text=False) == PROGRAM2_SHA256
        and all(
            sha256_file(inputs / name, normalize_text=False) == expected
            for name, expected in input_hashes.items()
        )
        and load_and_verify_integrity(root, integrity).passed
    )
    if not evidence_intact:
        verdict = "integrity_failed"
    summary = {
        "scope": "CMS July 2025, ten supplied SAS artifact comparisons",
        "program0_code_origin": "saved_model_candidate_after_automatic_repair",
        "program0_candidate_sha256": PROGRAM0_SHA256,
        "program0_report": program0_report.relative_to(root).as_posix(),
        "program1_code_origin": "human_reference",
        "program1_report": chain_path.relative_to(root).as_posix(),
        "program2_code_origin": "saved_model_candidate_with_manual_strict_correction",
        "original_program2_sha256": PROGRAM2_SHA256,
        "corrected_program2_sha256": corrected_hash,
        "program2_input_sha256": input_hashes,
        "program2_comparison_policy_sha256": PROGRAM2_POLICY_SHA256,
        "program2_execution": execution.status.value,
        "program2_report": "validation.json" if (run / "validation.json").exists() else None,
        "artifact_comparisons_passed": len(program0_result.validation_results)
        + len(DOMAINS)
        + passed_outputs,
        "status": verdict,
    }
    (run / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"July 2025 replay: {verdict}. {run / 'summary.json'}")
    return 0 if verdict == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program0_candidate", type=Path)
    parser.add_argument("program2_candidate", type=Path)
    parser.add_argument("--image", default="sasguard-runner:local")
    args = parser.parse_args()
    try:
        return replay(Path.cwd(), args.program0_candidate, args.program2_candidate, args.image)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Replay could not complete: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
