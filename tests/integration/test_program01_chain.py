"""Use human controls to test the real Program 0 to Program 1 Docker handoff."""

import os
import shutil
from pathlib import Path

import pytest

from sasguard.execution.program0 import (
    CandidateInputFormat,
    run_program0_candidate,
    validate_collected_program0,
)
from sasguard.prototypes.program01 import DOMAINS, run_program01_chain

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.docker_integration
def test_python_program0_output_feeds_all_five_program1_domains(tmp_path: Path) -> None:
    if os.environ.get("SASGUARD_RUN_DOCKER_TESTS") != "1" or shutil.which("docker") is None:
        pytest.skip("set SASGUARD_RUN_DOCKER_TESTS=1 with Docker available")
    image = os.environ.get("SASGUARD_TEST_RUNNER_IMAGE", "sasguard-runner:test")
    # A human-written control exercises the handoff without claiming model generation.
    source = (ROOT / "src/sasguard/program0.py").read_text(encoding="utf-8")
    source += """
import os
from pathlib import Path
inputs = Path(os.environ["SASGUARD_INPUT_DIR"])
output = Path(os.environ["SASGUARD_OUTPUT_DIR"])
frame = pd.read_csv(inputs / "alldata_2025jul.csv", converters={"PROVIDER_ID": str},
                    float_precision="round_trip")
result = translate_program0(frame)
for name, table in (
    ("less100_measure.csv", result.excluded_measures),
    ("measure_average_stddev_2025jul.csv", result.raw_statistics),
    ("std_data_2025jul_analysis.csv", result.analysis),
):
    table.to_csv(output / name, index=False, float_format="%.17g")
"""
    candidate = tmp_path / "human_control.py"
    candidate.write_text(source, encoding="utf-8")
    upstream, path = run_program0_candidate(
        ROOT,
        candidate,
        image=image,
        input_format=CandidateInputFormat.SAS7BDAT,
        validator=validate_collected_program0,
    )
    assert upstream.validation_status == "passed"
    result, report = run_program01_chain(ROOT, path.parent, image=image)
    assert result.status == "passed", result.model_dump_json(indent=2)
    assert set(result.comparisons) == set(DOMAINS)
    assert all(item.actual_rows == 4566 and item.passed for item in result.comparisons.values())
    assert all(item.passed for item in result.input_passthrough.values())
    assert result.program1_code_origin == "human_reference"
    assert not result.full_pipeline_verified
    # No supplied standardized intermediate or gold outputs are staged into this container.
    assert {entry.name for entry in (report.parent / "input").iterdir()} == {
        "std_data_2025jul_analysis.csv"
    }
    assert (
        result.input_path
        == (path.parent / "output/std_data_2025jul_analysis.csv").relative_to(ROOT).as_posix()
    )
    staged_input = report.parent / "input/std_data_2025jul_analysis.csv"
    assert (
        staged_input.read_bytes()
        == (path.parent / "output/std_data_2025jul_analysis.csv").read_bytes()
    )
    intermediate = path.parent / "output/std_data_2025jul_analysis.csv"
    original = intermediate.read_bytes()
    intermediate.write_bytes(original + b"\n")
    try:
        with pytest.raises(ValueError, match="requires a verified Program 0"):
            run_program01_chain(ROOT, path.parent, image=image)
    finally:
        intermediate.write_bytes(original)
