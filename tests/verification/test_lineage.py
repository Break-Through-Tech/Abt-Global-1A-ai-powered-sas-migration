"""Tests for canonical artifact lineage graphs."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sasguard.verification.lineage import ArtifactLineage, ArtifactNode


def _lineage(*nodes: ArtifactNode) -> ArtifactLineage:
    return ArtifactLineage(schema_version=1, nodes=nodes)


def test_equivalent_graphs_have_canonical_order_and_json() -> None:
    first = _lineage(
        ArtifactNode(name="final", parents=("middle",)),
        ArtifactNode(name="middle", parents=("source",)),
        ArtifactNode(name="source"),
    )
    reordered = _lineage(
        ArtifactNode(name="SOURCE"),
        ArtifactNode(name="MIDDLE", parents=("SOURCE",)),
        ArtifactNode(name="FINAL", parents=("MIDDLE",)),
    )

    assert first.ordered_names() == ("SOURCE", "MIDDLE", "FINAL")
    assert first.model_dump_json() == reordered.model_dump_json()


def test_lineage_names_are_case_insensitive_and_relationships_are_sorted() -> None:
    lineage = _lineage(
        ArtifactNode(name="report", parents=("left", "right")),
        ArtifactNode(name="right", parents=("root",)),
        ArtifactNode(name="left", parents=("root",)),
        ArtifactNode(name="root"),
    )

    assert lineage.ancestors("report") == ("ROOT", "LEFT", "RIGHT")
    assert lineage.descendants("root") == ("LEFT", "RIGHT", "REPORT")


def test_parent_order_is_canonicalized() -> None:
    first = _lineage(
        ArtifactNode(name="report", parents=("left", "right")),
        ArtifactNode(name="right"),
        ArtifactNode(name="left"),
    )
    second = _lineage(
        ArtifactNode(name="left"),
        ArtifactNode(name="right"),
        ArtifactNode(name="report", parents=("RIGHT", "LEFT")),
    )

    assert first.model_dump_json() == second.model_dump_json()


@pytest.mark.parametrize(
    "build_nodes",
    [
        lambda: (ArtifactNode(name="same"), ArtifactNode(name="SAME")),
        lambda: (ArtifactNode(name="child", parents=("absent",)),),
        lambda: (ArtifactNode(name="self", parents=("SELF",)),),
        lambda: (
            ArtifactNode(name="left", parents=("right",)),
            ArtifactNode(name="right", parents=("left",)),
        ),
        lambda: (ArtifactNode(name="child", parents=("root", "ROOT")), ArtifactNode(name="root")),
    ],
)
def test_invalid_lineage_graphs_are_rejected(
    build_nodes: Callable[[], tuple[ArtifactNode, ...]],
) -> None:
    with pytest.raises(ValueError):
        _lineage(*build_nodes())


@pytest.mark.parametrize(
    "build_lineage",
    [
        lambda: ArtifactLineage(schema_version=2, nodes=(ArtifactNode(name="root"),)),
        lambda: ArtifactLineage(nodes=()),
        lambda: ArtifactNode(name="not-valid"),
        lambda: ArtifactNode(name="root", unexpected="value"),
        lambda: _lineage(
            ArtifactNode(name="first", parents=("second",)),
            ArtifactNode(name="second", parents=("third",)),
            ArtifactNode(name="third", parents=("first",)),
        ),
    ],
)
def test_invalid_versions_empty_graphs_and_identifiers_are_rejected(
    build_lineage: Callable[[], object],
) -> None:
    with pytest.raises(ValueError):
        build_lineage()


def test_queries_reject_unknown_names() -> None:
    lineage = _lineage(ArtifactNode(name="known"))

    with pytest.raises(ValueError):
        lineage.ancestors("missing")
    with pytest.raises(ValueError):
        lineage.descendants("missing")
