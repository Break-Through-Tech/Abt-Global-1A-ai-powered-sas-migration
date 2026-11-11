"""Structural feedback survives malformed keys without disclosing row values."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from test_program0_reporting import bundle

from sasguard.config import load_project_configuration
from sasguard.data import ArtifactFormat, LoadedArtifact, load_artifact
from sasguard.execution.program0 import CandidateReport, CollectedArtifact
from sasguard.prototypes import program0_feedback as feedback
from sasguard.prototypes.program0_model import repair_diagnostics
from sasguard.provenance.hashing import sha256_file
from sasguard.verification import ArtifactComparisonPolicy
from sasguard.verification.program0 import PROGRAM0_ARTIFACTS

PRIVATE = "PRIVATE_PROVIDER_OR_VALUE_934827"


@pytest.fixture
def diagnostic_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run = bundle(tmp_path, state="malformed_outputs")
    saved = CandidateReport.model_validate_json((run / "report.json").read_bytes())
    tables = {
        "less100_measure.csv": "FREQ,MEASURE_NAME\n",
        "measure_average_stddev_2025jul.csv": f"_TYPE_,SCORE_MEAN,{PRIVATE}\n0,5,99\n",
        "std_data_2025jul_analysis.csv": (
            "PROVIDER_ID,STD_SCORE,COPIED_DEN\n001,1,100\nNA,,101\nNULL,-1,102\n"
        ),
    }
    artifacts = {}
    for name, text in tables.items():
        path = run / "output" / name
        path.write_text(text, encoding="utf-8")
        actual = load_artifact(path)
        artifacts[name] = CollectedArtifact(
            relative_path=f"output/{name}",
            sha256=sha256_file(path),
            rows=actual.row_count,
            columns=list(actual.columns),
        )
    policies = {
        "LESS100_MEASURE": ArtifactComparisonPolicy(keys=("MEASURE_NAME",)),
        "MEASURE_AVERAGE_STDDEV_2025JUL": ArtifactComparisonPolicy(keys=("_STAT_",)),
        "STD_DATA_2025JUL_ANALYSIS": ArtifactComparisonPolicy(keys=("PROVIDER_ID",)),
    }
    assert saved.validation_evidence is not None
    saved = saved.model_copy(
        update={
            "artifacts": artifacts,
            "validation_errors": {"measure_average_stddev_2025jul.csv": PRIVATE},
            "validation_evidence": saved.validation_evidence.model_copy(
                update={
                    "output_hashes": {name: item.sha256 for name, item in artifacts.items()},
                    "policies": policies,
                }
            ),
        }
    )
    expected_frames = {
        "LESS100_MEASURE": pd.DataFrame(columns=["FREQ", "MEASURE_NAME"]),
        "MEASURE_AVERAGE_STDDEV_2025JUL": pd.DataFrame(
            {
                "_TYPE_": [0] * 5,
                "_FREQ_": [3] * 5,
                "_STAT_": ["N", "MIN", "MAX", "MEAN", "STD"],
                "SCORE": [3, 1, 7, 4, 3],
            }
        ),
        "STD_DATA_2025JUL_ANALYSIS": pd.DataFrame(
            {
                "PROVIDER_ID": ["001", "NA", PRIVATE],
                "STD_SCORE": [1.1, None, -1.0],
                "COPIED_DEN": [100.5, 101, 102],
            }
        ),
    }

    def metadata(path: Path, **kwargs: object):
        assert kwargs == {"metadataonly": True}
        frame = expected_frames[path.stem.upper()]
        return None, SimpleNamespace(column_names=list(frame.columns), number_rows=len(frame))

    def load(path: Path, *, key: str):
        if path.suffix == ".csv":
            return load_artifact(path, key=key)
        return LoadedArtifact(
            frame=expected_frames[path.stem.upper()],
            source_path=path,
            format=ArtifactFormat.SAS7BDAT,
            key_column=key,
        )

    monkeypatch.setattr(feedback.pyreadstat, "read_sas7bdat", metadata)
    monkeypatch.setattr(feedback, "load_artifact", load)
    monkeypatch.setattr(feedback, "load_program0_policies", lambda root: policies)
    monkeypatch.setattr(
        feedback,
        "load_project_configuration",
        lambda path, **kwargs: load_project_configuration(
            path, project_root=tmp_path, require_existing=False
        ),
    )
    return tmp_path, run, saved


def test_feedback_identifies_missing_key_and_wrong_table_shape(diagnostic_run) -> None:
    root, run, saved = diagnostic_run
    result = feedback.structural_feedback(root, run / "output", saved)
    structure = result["artifact_structure"]["measure_average_stddev_2025jul.csv"]
    assert structure["missing_key_columns"] == ["_STAT_"]
    assert structure["expected_rows"] == 5 and structure["actual_rows"] == 1
    assert structure["missing_columns"] == ["_FREQ_", "_STAT_", "SCORE"]
    assert result["first_observed_failed_artifact"] == "measure_average_stddev_2025jul.csv"
    assert saved.validation_status == "malformed_outputs" and not saved.validation_results


def test_malformed_statistics_does_not_hide_other_numerical_failures(diagnostic_run) -> None:
    root, run, saved = diagnostic_run
    result = feedback.structural_feedback(root, run / "output", saved)
    comparisons = result["independent_artifact_comparisons"]
    assert comparisons["less100_measure.csv"]["passed"]
    assert comparisons["measure_average_stddev_2025jul.csv"]["status"] == "not_comparable"
    assert comparisons["std_data_2025jul_analysis.csv"]["status"] == "compared"
    assert not comparisons["std_data_2025jul_analysis.csv"]["passed"]
    assert comparisons["std_data_2025jul_analysis.csv"]["mismatched_cells"] == 2


def test_feedback_excludes_raw_keys_values_errors_and_untrusted_column_names(
    diagnostic_run,
) -> None:
    root, run, saved = diagnostic_run
    result = feedback.structural_feedback(root, run / "output", saved)
    text = json.dumps(result)
    assert PRIVATE not in text
    assert '"missing_key_count": 1' in text and '"extra_key_count": 1' in text
    assert '"unexpected_column_count": 2' in text
    assert "reference_metadata_source" in text


def test_feedback_is_read_only(diagnostic_run) -> None:
    root, run, saved = diagnostic_run
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    feedback.structural_feedback(root, run / "output", saved)
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("target", ["output", "source", "reference", "policy"])
def test_changed_diagnostic_inputs_fail_closed(diagnostic_run, target: str) -> None:
    root, run, saved = diagnostic_run
    if target == "output":
        path = run / "output" / next(iter(PROGRAM0_ARTIFACTS))
    elif target == "source":
        path = run / "source/main.py"
    elif target == "reference":
        path = next((root / "data/Project_1/SAS Output").glob("*.sas7bdat"))
    else:
        path = root / "configs/program0-comparison-policies.json"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="evidence changed"):
        feedback.structural_feedback(root, run / "output", saved)


def test_legacy_diagnostic_version_remains_reconstructable(diagnostic_run) -> None:
    root, run, saved = diagnostic_run
    legacy = repair_diagnostics(root, saved, run / "report.json", "program0-aggregate-v1")
    assert "artifact_structure" not in legacy and "diagnostic_version" not in legacy
    current = repair_diagnostics(root, saved, run / "report.json", "program0-aggregate-v2")
    assert current["diagnostic_version"] == "program0-aggregate-v2"
    with pytest.raises(ValueError, match="unsupported"):
        repair_diagnostics(root, saved, run / "report.json", "unknown")
