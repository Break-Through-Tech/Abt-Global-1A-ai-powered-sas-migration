"""Tests for scoped artifact verification traces."""

from __future__ import annotations

import json

import pytest

from sasguard.verification.artifact import ArtifactComparison
from sasguard.verification.golden_trace import (
    Checkpoint,
    GoldenTraceResult,
    trace_artifacts,
)
from sasguard.verification.lineage import ArtifactLineage, ArtifactNode


def _lineage(*nodes: ArtifactNode) -> ArtifactLineage:
    return ArtifactLineage(schema_version=1, nodes=nodes)


def _comparison(artifact: str, *, passed: bool = True) -> ArtifactComparison:
    return ArtifactComparison(
        artifact=artifact,
        passed=passed,
        reference_source="csv",
        expected_rows=2,
        actual_rows=2 if passed else 1,
        expected_columns=["PROVIDER_ID", "SCORE"],
        actual_columns=["PROVIDER_ID", "SCORE"],
        missing_keys=[] if passed else ["private-missing-key"],
        mismatched_columns=[] if passed else ["SCORE"],
        mismatched_cells=0 if passed else 1,
    )


def _status(result: GoldenTraceResult, artifact: str) -> str:
    checkpoint = next(item for item in result.checkpoints if item.artifact == artifact)
    return checkpoint.status.value


def test_all_passing_comparisons_confirm_complete_scope() -> None:
    lineage = _lineage(
        ArtifactNode(name="child", parents=("root",)),
        ArtifactNode(name="root"),
    )

    result = trace_artifacts(
        lineage,
        [_comparison("CHILD"), _comparison("ROOT")],
        scope="complete",
    )

    assert _status(result, "ROOT") == "passed"
    assert _status(result, "CHILD") == "passed"
    assert result.scope_complete
    assert result.all_checked_passed
    assert result.first_divergences == ()
    assert result.not_checked_artifacts == ()


def test_chain_failure_marks_only_earliest_observed_failure_as_frontier() -> None:
    lineage = _lineage(
        ArtifactNode(name="downstream", parents=("middle",)),
        ArtifactNode(name="middle", parents=("root",)),
        ArtifactNode(name="root"),
    )

    result = trace_artifacts(
        lineage,
        [
            _comparison("ROOT", passed=False),
            _comparison("MIDDLE", passed=False),
            _comparison("DOWNSTREAM"),
        ],
        scope="all",
    )

    assert [item.artifact for item in result.first_divergences] == ["ROOT"]
    assert result.first_divergences[0].dependent_artifacts == ("MIDDLE", "DOWNSTREAM")
    assert result.first_divergences[0].confirmed_within_scope
    assert _status(result, "MIDDLE") == "failed"
    assert _status(result, "DOWNSTREAM") == "passed"
    assert not result.all_checked_passed
    assert result.scope_complete


def test_independent_failures_on_diamond_branches_are_both_frontier_items() -> None:
    lineage = _lineage(
        ArtifactNode(name="joined", parents=("left", "right")),
        ArtifactNode(name="right", parents=("root",)),
        ArtifactNode(name="left", parents=("root",)),
        ArtifactNode(name="root"),
    )

    result = trace_artifacts(
        lineage,
        [
            _comparison(name, passed=name != "LEFT" and name != "RIGHT")
            for name in ("ROOT", "LEFT", "RIGHT")
        ],
        scope="branch-check",
    )

    assert [item.artifact for item in result.first_divergences] == ["LEFT", "RIGHT"]
    assert all(item.confirmed_within_scope for item in result.first_divergences)
    assert result.first_divergences[0].dependent_artifacts == ("JOINED",)
    assert result.first_divergences[1].dependent_artifacts == ("JOINED",)
    assert not result.scope_complete


def test_failed_downstream_with_unchecked_ancestor_is_unconfirmed() -> None:
    lineage = _lineage(
        ArtifactNode(name="child", parents=("root",)),
        ArtifactNode(name="root"),
    )

    result = trace_artifacts(lineage, [_comparison("CHILD", passed=False)], scope="partial")

    assert result.first_divergences[0].artifact == "CHILD"
    assert not result.first_divergences[0].confirmed_within_scope
    assert result.first_divergences[0].unchecked_upstream == ("ROOT",)
    assert result.not_checked_artifacts == ("ROOT",)
    assert not result.scope_complete


def test_explicit_reference_input_is_a_not_checked_boundary_and_can_confirm_scope() -> None:
    lineage = _lineage(
        ArtifactNode(name="derived", parents=("trusted_input",)),
        ArtifactNode(name="trusted_input"),
    )

    result = trace_artifacts(
        lineage,
        [_comparison("DERIVED", passed=False)],
        scope="derived-output",
        supplied_reference_inputs=("trusted_input",),
    )

    boundary = next(item for item in result.checkpoints if item.artifact == "TRUSTED_INPUT")
    assert boundary.status.value == "not_checked"
    assert boundary.supplied_reference_input
    assert result.not_checked_artifacts == ("TRUSTED_INPUT",)
    assert result.scope_complete
    assert result.first_divergences[0].confirmed_within_scope


def test_reference_boundary_cuts_failure_propagation_to_other_branches() -> None:
    lineage = _lineage(
        ArtifactNode(name="mortality", parents=("standardized",)),
        ArtifactNode(name="standardized", parents=("aldata",)),
        ArtifactNode(name="aldata"),
    )

    result = trace_artifacts(
        lineage,
        [_comparison("ALDATA", passed=False), _comparison("MORTALITY", passed=False)],
        scope="mortality-output",
        supplied_reference_inputs=("STANDARDIZED",),
    )

    assert [item.artifact for item in result.first_divergences] == ["ALDATA", "MORTALITY"]
    assert result.first_divergences[0].dependent_artifacts == ()
    assert result.first_divergences[1].unchecked_upstream == ()
    assert all(item.confirmed_within_scope for item in result.first_divergences)
    assert _status(result, "STANDARDIZED") == "not_checked"
    assert result.scope_complete


def test_independently_passed_child_keeps_its_status_after_parent_failure() -> None:
    lineage = _lineage(
        ArtifactNode(name="child", parents=("parent",)),
        ArtifactNode(name="parent"),
    )

    result = trace_artifacts(
        lineage,
        [_comparison("PARENT", passed=False), _comparison("CHILD")],
        scope="both",
    )

    assert _status(result, "PARENT") == "failed"
    assert _status(result, "CHILD") == "passed"


def test_partial_scope_can_have_all_checked_comparisons_pass() -> None:
    lineage = _lineage(
        ArtifactNode(name="child", parents=("root",)),
        ArtifactNode(name="root"),
    )

    result = trace_artifacts(lineage, [_comparison("ROOT")], scope="root-only")

    assert result.all_checked_passed
    assert not result.scope_complete
    assert result.not_checked_artifacts == ("CHILD",)


def test_result_validation_rejects_contradictory_summary_fields() -> None:
    lineage = _lineage(
        ArtifactNode(name="child", parents=("root",)),
        ArtifactNode(name="root"),
    )
    result = trace_artifacts(lineage, [_comparison("ROOT")], scope="root-only")
    payload = result.model_dump(mode="json")

    with pytest.raises(ValueError):
        GoldenTraceResult.model_validate({**payload, "all_checked_passed": False})
    with pytest.raises(ValueError):
        GoldenTraceResult.model_validate({**payload, "scope_complete": True})
    with pytest.raises(ValueError):
        GoldenTraceResult.model_validate(
            {**payload, "checkpoints": [*payload["checkpoints"], payload["checkpoints"][0]]}
        )


def test_checkpoint_validation_rejects_a_passed_reference_boundary() -> None:
    boundary = Checkpoint(
        artifact="trusted_input",
        parents=(),
        status="not_checked",
        supplied_reference_input=True,
    )

    with pytest.raises(ValueError):
        Checkpoint.model_validate({**boundary.model_dump(), "status": "passed"})


def test_result_validation_rejects_first_divergence_for_a_passing_checkpoint() -> None:
    lineage = _lineage(ArtifactNode(name="root"))
    failed = trace_artifacts(
        lineage,
        [_comparison("ROOT", passed=False)],
        scope="root",
    )
    payload = failed.model_dump(mode="json")
    payload["checkpoints"][0]["status"] = "passed"
    payload["all_checked_passed"] = True

    with pytest.raises(ValueError):
        GoldenTraceResult.model_validate(payload)


def test_no_comparisons_means_no_pass_claim_and_empty_scope_is_invalid() -> None:
    lineage = _lineage(ArtifactNode(name="root"))

    result = trace_artifacts(lineage, [], scope="root")

    assert not result.all_checked_passed
    assert not result.scope_complete
    assert result.not_checked_artifacts == ("ROOT",)
    with pytest.raises(ValueError):
        trace_artifacts(lineage, [], scope=" ")


@pytest.mark.parametrize(
    ("comparisons", "boundaries"),
    [
        ([_comparison("UNKNOWN")], ()),
        ([_comparison("ROOT"), _comparison("root")], ()),
        ([], ("unknown",)),
        ([_comparison("ROOT")], ("root",)),
        ([], ("ROOT", "root")),
    ],
)
def test_unknown_duplicate_or_overlapping_inputs_are_rejected(
    comparisons: list[ArtifactComparison], boundaries: tuple[str, ...]
) -> None:
    lineage = _lineage(ArtifactNode(name="root"))

    with pytest.raises(ValueError):
        trace_artifacts(
            lineage,
            comparisons,
            scope="root",
            supplied_reference_inputs=boundaries,
        )


def test_equivalent_input_orders_produce_identical_canonical_results() -> None:
    lineage_a = _lineage(
        ArtifactNode(name="child", parents=("root",)),
        ArtifactNode(name="root"),
    )
    lineage_b = _lineage(ArtifactNode(name="ROOT"), ArtifactNode(name="CHILD", parents=("ROOT",)))

    first = trace_artifacts(lineage_a, [_comparison("CHILD"), _comparison("ROOT")], scope="all")
    second = trace_artifacts(lineage_b, [_comparison("ROOT"), _comparison("CHILD")], scope="all")

    assert first.to_json() == second.to_json()


@pytest.mark.parametrize("kept", [0, 1])
def test_saved_result_cannot_omit_independent_observed_failures(kept: int) -> None:
    from sasguard.verification.golden_trace import GoldenTraceResult

    lineage = _lineage(
        ArtifactNode(name="ROOT"),
        ArtifactNode(name="LEFT", parents=("ROOT",)),
        ArtifactNode(name="RIGHT", parents=("ROOT",)),
    )
    result = trace_artifacts(
        lineage,
        [
            _comparison("ROOT"),
            _comparison("LEFT", passed=False),
            _comparison("RIGHT", passed=False),
        ],
        scope="independent failures",
    )
    payload = result.model_dump(mode="json")
    payload["first_divergences"] = payload["first_divergences"][:kept]
    with pytest.raises(ValueError, match="complete observed failure frontier"):
        GoldenTraceResult.model_validate(payload)


def test_saved_result_cannot_hide_unchecked_upstream_to_claim_confirmation() -> None:
    from sasguard.verification.golden_trace import GoldenTraceResult

    result = trace_artifacts(
        _lineage(ArtifactNode(name="ROOT"), ArtifactNode(name="CHILD", parents=("ROOT",))),
        [_comparison("CHILD", passed=False)],
        scope="unchecked upstream",
    )
    payload = result.model_dump(mode="json")
    payload["first_divergences"][0]["unchecked_upstream"] = []
    payload["first_divergences"][0]["confirmed_within_scope"] = True
    with pytest.raises(ValueError, match="checkpoint evidence"):
        GoldenTraceResult.model_validate(payload)


def test_saved_result_cannot_omit_dependent_artifacts() -> None:
    from sasguard.verification.golden_trace import GoldenTraceResult

    result = trace_artifacts(
        _lineage(ArtifactNode(name="ROOT"), ArtifactNode(name="CHILD", parents=("ROOT",))),
        [_comparison("ROOT", passed=False)],
        scope="dependent checkpoints",
    )
    payload = result.model_dump(mode="json")
    payload["first_divergences"][0]["dependent_artifacts"] = []
    with pytest.raises(ValueError, match="effective lineage"):
        GoldenTraceResult.model_validate(payload)


def test_diagnostics_exclude_key_values_but_include_column_names() -> None:
    lineage = _lineage(ArtifactNode(name="sensitive_output"))
    comparison = _comparison("SENSITIVE_OUTPUT", passed=False).model_copy(
        update={
            "missing_keys": ["private-missing-key"],
            "extra_keys": ["private-extra-provider-id"],
            "mismatched_columns": ["SAFE_TO_REPORT_COLUMN"],
        }
    )

    result = trace_artifacts(lineage, [comparison], scope="output")
    serialized = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    assert "private-missing-key" not in serialized
    assert "private-extra-provider-id" not in serialized
    assert "SAFE_TO_REPORT_COLUMN" in serialized
    assert "csv" in serialized
