"""Validated dependency graphs for generated artifacts."""

import re
from heapq import heapify, heappop, heappush
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SAS_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")


def canonicalize_identifier(value: str) -> str:
    """Return the uppercase form of a valid SAS identifier."""
    if not isinstance(value, str) or not _SAS_IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid SAS identifier: {value!r}")
    return value.upper()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactNode(StrictModel):
    """One artifact and the artifacts that must exist before it."""

    name: str
    parents: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def canonical_name(cls, value: str) -> str:
        return canonicalize_identifier(value)

    @field_validator("parents")
    @classmethod
    def canonical_parents(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        canonical = tuple(canonicalize_identifier(value) for value in values)
        if len(set(canonical)) != len(canonical):
            raise ValueError("parent names must be unique after canonicalization")
        return tuple(sorted(canonical))


class ArtifactLineage(StrictModel):
    """A versioned, deterministic dependency graph."""

    schema_version: int = Field(default=1, ge=1, le=1)
    nodes: tuple[ArtifactNode, ...] = Field(min_length=1)

    @field_validator("nodes")
    @classmethod
    def canonical_nodes(cls, values: tuple[ArtifactNode, ...]) -> tuple[ArtifactNode, ...]:
        return tuple(sorted(values, key=lambda node: node.name))

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        by_name: dict[str, ArtifactNode] = {}
        for node in self.nodes:
            if node.name in by_name:
                raise ValueError(f"duplicate artifact name: {node.name}")
            by_name[node.name] = node
        for node in self.nodes:
            if node.name in node.parents:
                raise ValueError(f"artifact cannot depend on itself: {node.name}")
            unknown = set(node.parents) - by_name.keys()
            if unknown:
                raise ValueError(f"unknown parents for {node.name}: {sorted(unknown)}")
        self._topological_order(by_name)
        return self

    @staticmethod
    def _topological_order(nodes: dict[str, ArtifactNode]) -> tuple[str, ...]:
        children: dict[str, list[str]] = {name: [] for name in nodes}
        indegree = {name: len(node.parents) for name, node in nodes.items()}
        for name, node in nodes.items():
            for parent in node.parents:
                children[parent].append(name)
        ready = [name for name, degree in indegree.items() if degree == 0]
        heapify(ready)
        ordered: list[str] = []
        while ready:
            name = heappop(ready)
            ordered.append(name)
            for child in sorted(children[name]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    heappush(ready, child)
        if len(ordered) != len(nodes):
            raise ValueError("artifact lineage contains a cycle")
        return tuple(ordered)

    def ordered_names(self) -> tuple[str, ...]:
        """Return a lexically tie-broken topological order."""
        return self._topological_order({node.name: node for node in self.nodes})

    def ancestors(self, name: str) -> tuple[str, ...]:
        """Return all ancestors in deterministic topological order."""
        target = canonicalize_identifier(name)
        by_name = {node.name: node for node in self.nodes}
        if target not in by_name:
            raise ValueError(f"unknown artifact: {target}")
        found: set[str] = set()
        pending = list(by_name[target].parents)
        while pending:
            parent = pending.pop()
            if parent not in found:
                found.add(parent)
                pending.extend(by_name[parent].parents)
        return tuple(item for item in self.ordered_names() if item in found)

    def descendants(self, name: str) -> tuple[str, ...]:
        """Return all descendants in deterministic topological order."""
        target = canonicalize_identifier(name)
        by_name = {node.name: node for node in self.nodes}
        if target not in by_name:
            raise ValueError(f"unknown artifact: {target}")
        children: dict[str, list[str]] = {key: [] for key in by_name}
        for node in self.nodes:
            for parent in node.parents:
                children[parent].append(node.name)
        found: set[str] = set()
        pending = list(children[target])
        while pending:
            child = pending.pop()
            if child not in found:
                found.add(child)
                pending.extend(children[child])
        return tuple(item for item in self.ordered_names() if item in found)
