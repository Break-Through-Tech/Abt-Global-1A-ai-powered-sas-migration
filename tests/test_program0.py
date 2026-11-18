"""Small cases for the Program 0 translation."""

import math
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from sasguard.cli import app
from sasguard.program0 import Program0Spec, translate_program0

runner = CliRunner()


def test_exclusion_hospital_filter_and_reversal() -> None:
    input_data = pd.DataFrame(
        {
            "PROVIDER_ID": ["a", "b", "c"],
            "A": [1.0, 3.0, None],
            "B": [None, 4.0, None],
            "PASSTHROUGH": [10.0, 20.0, 30.0],
        }
    )
    original = input_data.copy(deep=True)
    spec = Program0Spec(("A", "B"), frozenset({"A"}), minimum_reporting_count=2)

    result = translate_program0(input_data, spec=spec)

    pd.testing.assert_frame_equal(input_data, original)
    assert result.active_measures == ("A",)
    assert result.excluded_measures.to_dict("records") == [{"freq": 1.0, "measure_name": "B"}]
    assert list(result.analysis.columns) == ["PROVIDER_ID", "PASSTHROUGH", "Total_m_cnt", "std_A"]
    assert result.analysis["PROVIDER_ID"].tolist() == ["a", "b"]
    assert result.analysis["Total_m_cnt"].tolist() == [1, 1]
    assert result.analysis["std_A"].tolist() == pytest.approx([1 / math.sqrt(2), -1 / math.sqrt(2)])
    assert result.raw_statistics["_STAT_"].tolist() == ["N", "MIN", "MAX", "MEAN", "STD"]
    assert result.raw_statistics["A"].tolist() == pytest.approx([2, 1, 3, 2, math.sqrt(2)])


def test_input_column_case_is_resolved_without_changing_the_input() -> None:
    input_data = pd.DataFrame({"provider_id": ["a", "b"], "measure": [1.0, 3.0]})
    spec = Program0Spec(("MEASURE",), frozenset(), minimum_reporting_count=1)

    result = translate_program0(input_data, spec=spec)

    assert list(input_data.columns) == ["provider_id", "measure"]
    assert list(result.analysis.columns) == ["PROVIDER_ID", "Total_m_cnt", "std_MEASURE"]


def test_input_rejects_case_collisions_and_missing_measures() -> None:
    spec = Program0Spec(("A",), frozenset(), minimum_reporting_count=1)
    collision = pd.DataFrame({"PROVIDER_ID": ["a"], "A": [1.0], "a": [2.0]})
    missing = pd.DataFrame({"PROVIDER_ID": ["a"], "B": [1.0]})

    with pytest.raises(ValueError, match="collide ignoring case"):
        translate_program0(collision, spec=spec)
    with pytest.raises(ValueError, match="missing measures"):
        translate_program0(missing, spec=spec)


def test_input_rejects_generated_column_collisions() -> None:
    spec = Program0Spec(("A",), frozenset(), minimum_reporting_count=1)
    input_data = pd.DataFrame({"PROVIDER_ID": ["a", "b"], "A": [1.0, 3.0], "std_A": [0, 0]})

    with pytest.raises(ValueError, match="generated columns"):
        translate_program0(input_data, spec=spec)


@pytest.mark.parametrize(
    ("measures", "reversed_measures", "minimum", "message"),
    [
        (("A", "a"), frozenset(), 1, "unique ignoring case"),
        (("a",), frozenset(), 1, "canonical uppercase"),
        (("A",), frozenset({"B"}), 1, "reversed measures"),
        (("A",), frozenset(), 0, "must be positive"),
    ],
)
def test_invalid_program0_spec_is_rejected(
    measures: tuple[str, ...], reversed_measures: frozenset[str], minimum: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Program0Spec(measures, reversed_measures, minimum)


def test_input_requires_text_columns_and_provider_identifier() -> None:
    spec = Program0Spec(("A",), frozenset(), minimum_reporting_count=1)
    nontext_column = pd.DataFrame({0: ["a"], "A": [1.0]})
    missing_provider = pd.DataFrame({"A": [1.0]})

    with pytest.raises(ValueError, match="column names must be strings"):
        translate_program0(nontext_column, spec=spec)
    with pytest.raises(ValueError, match="missing PROVIDER_ID"):
        translate_program0(missing_provider, spec=spec)


def test_all_measures_excluded_is_reported() -> None:
    spec = Program0Spec(("A",), frozenset(), minimum_reporting_count=2)
    input_data = pd.DataFrame({"PROVIDER_ID": ["a", "b"], "A": [1.0, None]})

    with pytest.raises(ValueError, match="no measures remain"):
        translate_program0(input_data, spec=spec)


def test_undefined_standardization_fails_instead_of_claiming_parity() -> None:
    spec = Program0Spec(("A",), frozenset(), minimum_reporting_count=1)
    constant = pd.DataFrame({"PROVIDER_ID": ["a", "b"], "A": [2.0, 2.0]})

    with pytest.raises(ValueError, match="zero variance"):
        translate_program0(constant, spec=spec)


def test_cli_rejects_output_outside_reports(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run-program0",
            "--project-root",
            str(tmp_path),
            "--output-directory",
            str(tmp_path / "data"),
        ],
    )

    assert result.exit_code == 2
    assert "reports/runs" in result.output


def test_cli_refuses_to_overwrite_generated_output(tmp_path: Path) -> None:
    output = tmp_path / "reports" / "runs" / "program0"
    output.mkdir(parents=True)
    (output / "less100_measure.csv").write_text("existing", encoding="utf-8")

    result = runner.invoke(app, ["run-program0", "--project-root", str(tmp_path)])

    assert result.exit_code == 2
    assert "already exists" in result.output
    assert (output / "less100_measure.csv").read_text(encoding="utf-8") == "existing"
