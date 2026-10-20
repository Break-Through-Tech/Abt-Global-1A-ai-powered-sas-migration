"""Check separate case selection and handwritten expectations without any model calls."""

import csv
import io
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from sasguard import cli
from sasguard.data import load_artifact
from sasguard.prototypes.local_model_cases import CASES
from sasguard.prototypes.local_model_holdout import HOLDOUT_CASES
from sasguard.prototypes.local_model_validation import (
    NUMERIC_COLUMNS,
    numeric_policy,
    select_cases,
)
from sasguard.verification import compare_artifacts


def test_holdout_is_separate_and_prompt_contains_no_rows() -> None:
    assert not set(CASES) & set(HOLDOUT_CASES)
    assert select_cases("development") is CASES
    assert select_cases("holdout-v1") is HOLDOUT_CASES
    for fixture in HOLDOUT_CASES.values():
        assert fixture.sas_source in fixture.prompt
        assert fixture.input_csv not in fixture.prompt
        assert fixture.expected_csv not in fixture.prompt
        assert fixture.name not in CASES
        assert set(numeric_policy(fixture).keys) == {fixture.key}
    with pytest.raises(ValueError, match="unknown case set"):
        select_cases("typo")


@pytest.mark.parametrize("name", list(HOLDOUT_CASES))
def test_handwritten_oracle_with_independent_scalar_calculations(name: str, tmp_path: Path) -> None:
    """Use scalar Python and CSV, not the pandas compatibility helpers, as a cross-check."""
    fixture = HOLDOUT_CASES[name]
    rows = list(csv.DictReader(io.StringIO(fixture.input_csv)))
    result = []
    if name == "holdout-grouped-keys":
        groups: dict[str, list[float]] = {}
        for row in rows:
            values = groups.setdefault(row["GROUP"], [])
            if row["SCORE"] != "":
                values.append(float(row["SCORE"]))
        result = [
            {
                "GROUP": key,
                "COUNT": len(values),
                "MEAN": sum(values) / len(values) if values else None,
            }
            for key, values in groups.items()
        ]
    else:
        for row in rows:
            output: dict[str, object] = {
                key: (value if key == fixture.key else float(value) if value != "" else None)
                for key, value in row.items()
            }
            if name == "holdout-sum-three":
                values = [float(row[key]) if row[key] != "" else None for key in ("A", "B", "C")]
                present = [value for value in values if value is not None]
                output["ARITH_TOTAL"] = sum(present) if len(present) == 3 else None
                output["FUNC_TOTAL"] = sum(present) if present else None
            else:
                score = float(row["SCORE"]) if row["SCORE"] != "" else None
                if name == "holdout-threshold":
                    output["FLAG"] = int(score is None or score < 5)
                else:
                    output["ADJUSTED"] = None if score is None else score * 1.5 - 2
            result.append(output)
    actual_path, expected_path = tmp_path / "actual.csv", tmp_path / "expected.csv"
    expected_path.write_text(fixture.expected_csv, encoding="utf-8")
    pd.DataFrame(result).to_csv(actual_path, index=False)
    assert compare_artifacts(
        load_artifact(actual_path, key=fixture.key),
        load_artifact(expected_path, key=fixture.key),
        artifact=name,
        policy=numeric_policy(fixture),
    ).passed
    assert set(NUMERIC_COLUMNS[name]) == set(load_artifact(expected_path).columns) - {fixture.key}


@pytest.mark.parametrize("command", ["local-model-smoke", "local-model-suite"])
def test_cli_forwards_separate_case_set(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def run(*args: object, **kwargs: object) -> tuple[bool, Path]:
        calls.append(kwargs)
        return True, Path("report.json")

    monkeypatch.setattr(cli, "run_local_model_smoke", run)
    monkeypatch.setattr(cli, "run_local_model_suite", run)
    args = [command, "--case-set", "holdout-v1"]
    if command == "local-model-smoke":
        args.extend(["--case", "holdout-threshold"])
    assert CliRunner().invoke(cli.app, args).exit_code == 0
    assert calls[0]["case_set"] == "holdout-v1"
