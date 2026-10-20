"""Independent examples for the bounded SAS compatibility functions."""

from pathlib import Path

import pandas as pd
import pytest

from sasguard.compatibility import read_sas_csv, sas_lt, sas_sum


def test_read_preserves_text_keys_and_numeric_missing(tmp_path: Path) -> None:
    path = tmp_path / "scores.csv"
    path.write_text("provider_id,value\n00190,8\nNA,\nNULL,-7\n,3\n", encoding="utf-8")
    frame = read_sas_csv(path)
    assert list(frame.columns) == ["PROVIDER_ID", "VALUE"]
    assert frame["PROVIDER_ID"].iloc[:3].tolist() == ["00190", "NA", "NULL"]
    assert pd.isna(frame["PROVIDER_ID"].iloc[3])
    assert pd.isna(frame["VALUE"].iloc[1])
    assert frame["VALUE"].iloc[2] == -7


def test_explicit_key_and_summary_without_provider_id(tmp_path: Path) -> None:
    path = tmp_path / "summary.csv"
    path.write_text("group,value\nNULL,2\nNA,\n0003,4\n", encoding="utf-8")
    frame = read_sas_csv(path, key="GROUP")
    assert frame["GROUP"].tolist() == ["NULL", "NA", "0003"]
    with pytest.raises(ValueError, match="not found"):
        read_sas_csv(path, key="MISSING_KEY")
    with pytest.raises(ValueError, match="CSV file"):
        read_sas_csv(tmp_path / "not.csv.sas7bdat")


@pytest.mark.parametrize("dtype", ["float64", "Float64"])
def test_less_than_uses_missing_order_and_preserves_index(dtype: str) -> None:
    values = pd.Series([float("nan"), -8, 4, 9], index=[20, 40, 50, 80], dtype=dtype)
    expected = pd.Series([True, True, False, False], index=values.index)
    pd.testing.assert_series_equal(sas_lt(values, 4).astype(bool), expected)
    assert values.isna().tolist() == [True, False, False, False]


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), -float("inf")])
def test_less_than_rejects_unsupported_thresholds(threshold: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        sas_lt(pd.Series([2.0]), threshold)


@pytest.mark.parametrize("dtype", ["float64", "Float64"])
def test_sum_distinguishes_all_missing_from_zero_and_plus(dtype: str) -> None:
    frame = pd.DataFrame(
        {"X": [7, None, None, -7, None], "Y": [None, 0, None, 7, 3]},
        index=[8, 4, 7, 1, 9],
        dtype=dtype,
    )
    original = frame.copy()
    actual = sas_sum(frame)
    assert actual.index.tolist() == [8, 4, 7, 1, 9]
    assert actual.iloc[[0, 1, 3, 4]].tolist() == [7, 0, 0, 3]
    assert pd.isna(actual.iloc[2])
    assert pd.isna((frame["X"] + frame["Y"]).iloc[0])
    pd.testing.assert_frame_equal(frame, original)


def test_sum_accepts_multiple_columns_and_empty_numeric_frame() -> None:
    frame = pd.DataFrame({"A": [3.0], "B": [None], "C": [4.0]}, dtype=float)
    assert sas_sum(frame).tolist() == [7]
    assert sas_sum(frame.iloc[:0]).empty
    with pytest.raises(ValueError, match="at least two"):
        sas_sum(frame[["A"]])


@pytest.mark.parametrize("values", [["2", "3"], [True, False]])
def test_numeric_helpers_reject_character_and_boolean_columns(values: list[object]) -> None:
    series = pd.Series(values)
    with pytest.raises(ValueError, match="numeric, non-boolean"):
        sas_lt(series, 0)
    with pytest.raises(ValueError, match="numeric, non-boolean"):
        sas_sum(pd.DataFrame({"A": series, "B": [1, 2]}))
