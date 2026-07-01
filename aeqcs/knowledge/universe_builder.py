"""Deterministic universe graph builder.

This module only accepts audited, explicit graph mutations. It does not call
external inference engines, infer missing entities, or generate candidate
relations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


class UniverseError(ValueError):
    """Raised when a universe graph mutation violates deterministic rules."""


GENERIC_PARENT_LEVELS = {"generic", "root", "unknown"}
GENERIC_PARENT_LABELS = {
    "all",
    "generic",
    "market",
    "misc",
    "other",
    "others",
    "root",
    "unknown",
    "全部",
    "其他",
    "市场",
    "概念",
    "板块",
    "行业",
    "证券",
    "股票",
    "主题",
}


@dataclass(frozen=True)
class UniverseNode:
    node_id: str
    label: str
    level: str
    created_by: str
    as_of_date: date
    status: str = "active"

    def to_record(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "level": self.level,
            "created_by": self.created_by,
            "as_of_date": self.as_of_date.isoformat(),
            "status": self.status,
        }


@dataclass
class UniverseEdge:
    edge_id: int
    parent_id: str
    child_id: str
    relation_type: str
    created_by: str
    as_of_date: date
    verified: bool = False
    verified_by: str | None = None
    verified_as_of: date | None = None
    retired_by: str | None = None
    valid_to: date | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "parent_id": self.parent_id,
            "child_id": self.child_id,
            "relation_type": self.relation_type,
            "created_by": self.created_by,
            "as_of_date": self.as_of_date.isoformat(),
            "verified": self.verified,
            "verified_by": self.verified_by,
            "verified_as_of": self.verified_as_of.isoformat() if self.verified_as_of else None,
            "retired_by": self.retired_by,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
        }


def _require_identity(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise UniverseError(f"{field} must be a string")
    if not value.strip():
        raise UniverseError(f"{field} is required")


def normalize_universe_label(label: str) -> str:
    return "".join(char.lower() for char in label if char.isalnum())


def is_generic_parent_values(label: str, level: str) -> bool:
    return (
        normalize_universe_label(level) in GENERIC_PARENT_LEVELS
        or normalize_universe_label(label) in GENERIC_PARENT_LABELS
    )


def is_generic_parent_node(node: UniverseNode) -> bool:
    return is_generic_parent_values(node.label, node.level)


class UniverseBuilder:
    """In-memory deterministic graph builder for tests and local workflows."""

    def __init__(self) -> None:
        self._nodes: dict[str, UniverseNode] = {}
        self._edges: dict[int, UniverseEdge] = {}
        self._next_edge_id = 1

    def add_node(
        self,
        node_id: str,
        label: str,
        level: str,
        created_by: str,
        as_of_date: date,
    ) -> dict[str, Any]:
        _require_identity(node_id, "node_id")
        _require_identity(label, "label")
        _require_identity(level, "level")
        _require_identity(created_by, "created_by")
        if node_id in self._nodes:
            raise UniverseError(f"node already exists: {node_id}")
        normalized_label = normalize_universe_label(label)
        if any(normalize_universe_label(node.label) == normalized_label for node in self._nodes.values()):
            raise UniverseError(f"synonym duplicate node label: {label}")
        node = UniverseNode(node_id, label, level, created_by, as_of_date)
        self._nodes[node_id] = node
        return node.to_record()

    def add_edge(
        self,
        parent_id: str,
        child_id: str,
        relation_type: str,
        created_by: str,
        as_of_date: date,
    ) -> dict[str, Any]:
        _require_identity(parent_id, "parent_id")
        _require_identity(child_id, "child_id")
        _require_identity(relation_type, "relation_type")
        _require_identity(created_by, "created_by")
        if parent_id not in self._nodes:
            raise UniverseError("parent node does not exist")
        if child_id not in self._nodes:
            raise UniverseError("child node does not exist")
        if is_generic_parent_node(self._nodes[parent_id]):
            raise UniverseError("parent node is too generic")
        edge = UniverseEdge(
            edge_id=self._next_edge_id,
            parent_id=parent_id,
            child_id=child_id,
            relation_type=relation_type,
            created_by=created_by,
            as_of_date=as_of_date,
        )
        self._edges[edge.edge_id] = edge
        self._next_edge_id += 1
        return edge.to_record()

    def verify_edge(self, edge_id: int, verified_by: str, as_of_date: date) -> dict[str, Any]:
        _require_identity(verified_by, "verified_by")
        edge = self._get_edge(edge_id)
        if as_of_date < edge.as_of_date:
            raise UniverseError("verified_as_of cannot be before edge as_of_date")
        edge.verified = True
        edge.verified_by = verified_by
        edge.verified_as_of = as_of_date
        return edge.to_record()

    def retire_edge(self, edge_id: int, retired_by: str, as_of_date: date) -> dict[str, Any]:
        _require_identity(retired_by, "retired_by")
        edge = self._get_edge(edge_id)
        if edge.verified_as_of is not None and as_of_date < edge.verified_as_of:
            raise UniverseError("valid_to cannot be before verified_as_of")
        edge.retired_by = retired_by
        edge.valid_to = as_of_date
        return edge.to_record()

    def children_as_of(self, parent_id: str, as_of_date: date) -> list[str]:
        _require_identity(parent_id, "parent_id")
        edges = [
            edge
            for edge in self._edges.values()
            if edge.parent_id == parent_id
            and edge.verified
            and edge.verified_as_of is not None
            and edge.verified_as_of <= as_of_date
            and (edge.valid_to is None or edge.valid_to > as_of_date)
        ]
        edges.sort(key=lambda edge: (edge.child_id, edge.edge_id))
        return [edge.child_id for edge in edges]

    def _get_edge(self, edge_id: int) -> UniverseEdge:
        try:
            return self._edges[edge_id]
        except KeyError as exc:
            raise UniverseError(f"edge does not exist: {edge_id}") from exc
