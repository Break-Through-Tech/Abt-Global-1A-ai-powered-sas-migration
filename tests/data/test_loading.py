"""Tests for canonical CSV and SAS7BDAT artifact loading."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sasguard.config import load_project_configuration
from sasguard.data import ArtifactFormat, ArtifactLoadError, load_artifact


def test_csv_preserves_identifier_text_and_numeric_missingness(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.csv"
    original = "provider_id,score,label\n00123,1.5,A\n00007,,\n"
    source.write_text(original, encoding="utf-8")

    artifact = load_artifact(source, key="PROVIDER_ID")

    assert artifact.format is ArtifactFormat.CSV
    assert artifact.key_column == "provider_id"
    assert artifact.frame["provider_id"].dtype == pd.StringDtype()
    assert artifact.frame["provider_id"].tolist() == ["00123", "00007"]
    assert pd.isna(artifact.frame.loc[1, "score"])
    assert artifact.frame.loc[0, "score"] == 1.5
    assert source.read_text(encoding="utf-8") == original
    assert "frame=" not in repr(artifact)
    assert "00123" not in repr(artifact)


def test_missing_text_key_remains_missing_instead_of_becoming_text(tmp_path: Path) -> None:
    source = tmp_path / "missing-key.csv"
    source.write_text("PROVIDER_ID,score\n00123,1\n,2\n", encoding="utf-8")

    artifact = load_artifact(source, key="provider_id")

    assert artifact.frame["PROVIDER_ID"].iloc[0] == "00123"
    assert pd.isna(artifact.frame["PROVIDER_ID"].iloc[1])


def test_csv_identifier_that_looks_like_default_na_remains_text(tmp_path: Path) -> None:
    source = tmp_path / "na-identifier.csv"
    source.write_text("PROVIDER_ID,score\nNA,\nN/A,1\n", encoding="utf-8")

    artifact = load_artifact(source, key="PROVIDER_ID")

    assert artifact.frame["PROVIDER_ID"].tolist() == ["NA", "N/A"]
    assert pd.isna(artifact.frame["score"].iloc[0])


@pytest.mark.parametrize(
    ("contents", "match"),
    [
        ("other,score\n00123,1\n", "comparison column not found"),
        (
            "provider_id,PROVIDER_ID,score\n00123,00123,1\n",
            "ambiguous case-insensitive column",
        ),
        ("", "CSV artifact has no header"),
    ],
)
def test_csv_rejects_missing_or_ambiguous_key_columns(
    tmp_path: Path, contents: str, match: str
) -> None:
    source = tmp_path / "invalid.csv"
    source.write_text(contents, encoding="utf-8")

    with pytest.raises(ArtifactLoadError, match=match):
        load_artifact(source, key="PROVIDER_ID")


def test_numeric_looking_csv_identifier_is_loaded_as_text(tmp_path: Path) -> None:
    source = tmp_path / "numeric-key.csv"
    source.write_text("PROVIDER_ID,score\n123,1\n", encoding="utf-8")

    artifact = load_artifact(source, key="PROVIDER_ID")

    assert artifact.frame["PROVIDER_ID"].tolist() == ["123"]


def test_numeric_sas_identifier_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "numeric-key.sas7bdat"
    source.write_bytes(b"synthetic test placeholder")

    def fake_sas_reader(_path: Path) -> tuple[pd.DataFrame, object]:
        return pd.DataFrame({"PROVIDER_ID": [123], "score": [1.0]}), object()

    monkeypatch.setattr("sasguard.data.loading.pyreadstat.read_sas7bdat", fake_sas_reader)

    with pytest.raises(ArtifactLoadError, match="must be textual"):
        load_artifact(source, key="PROVIDER_ID")


def test_missing_and_unsupported_files_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="artifact file does not exist"):
        load_artifact(tmp_path / "missing.csv", key="PROVIDER_ID")

    unsupported = tmp_path / "artifact.parquet"
    unsupported.write_bytes(b"not a table")
    with pytest.raises(ArtifactLoadError, match="unsupported artifact format"):
        load_artifact(unsupported, key="PROVIDER_ID")


def test_supplied_csv_and_sas_inputs_load_with_equivalent_schemas() -> None:
    project_root = Path(__file__).resolve().parents[2]
    configuration = load_project_configuration(
        project_root / "configs" / "cms_2025jul.yaml",
        project_root=project_root,
    )
    paths = configuration.resolve_paths(project_root)

    csv_artifact = load_artifact(paths.input_csv, key=configuration.project.key)
    sas_artifact = load_artifact(paths.input_sas7bdat, key=configuration.project.key)

    assert csv_artifact.key_column == "PROVIDER_ID"
    assert sas_artifact.key_column == "PROVIDER_ID"
    assert csv_artifact.frame["PROVIDER_ID"].dtype == pd.StringDtype()
    assert sas_artifact.frame["PROVIDER_ID"].dtype == pd.StringDtype()
    assert csv_artifact.row_count == sas_artifact.row_count
    assert csv_artifact.columns == sas_artifact.columns
    assert csv_artifact.row_count > 0
