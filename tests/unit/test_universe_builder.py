from datetime import date

import pytest

from aeqcs.knowledge.universe_builder import UniverseBuilder, UniverseError


def test_universe_builder_creates_manual_nodes_with_audit_fields():
    builder = UniverseBuilder()

    node = builder.add_node(
        node_id="concept.ai",
        label="AI",
        level="concept",
        created_by="data_steward",
        as_of_date=date(2026, 1, 2),
    )

    assert node == {
        "node_id": "concept.ai",
        "label": "AI",
        "level": "concept",
        "created_by": "data_steward",
        "as_of_date": "2026-01-02",
        "status": "active",
    }


def test_universe_builder_rejects_non_string_identity_fields():
    builder = UniverseBuilder()

    with pytest.raises(UniverseError, match="node_id must be a string"):
        builder.add_node(123, "AI", "concept", "data_steward", date(2026, 1, 2))

    with pytest.raises(UniverseError, match="relation_type must be a string"):
        builder.add_edge("concept.ai", "stock.000001", ["contains"], "data_steward", date(2026, 1, 2))


def test_universe_builder_rejects_edges_for_missing_nodes():
    builder = UniverseBuilder()
    builder.add_node(
        node_id="concept.ai",
        label="AI",
        level="concept",
        created_by="data_steward",
        as_of_date=date(2026, 1, 2),
    )

    with pytest.raises(UniverseError, match="child node does not exist"):
        builder.add_edge(
            parent_id="concept.ai",
            child_id="stock.000001",
            relation_type="contains",
            created_by="data_steward",
            as_of_date=date(2026, 1, 2),
        )


def test_universe_builder_returns_verified_edges_as_of_date():
    builder = UniverseBuilder()
    builder.add_node("concept.ai", "AI", "concept", "data_steward", date(2026, 1, 1))
    builder.add_node("stock.000001", "Ping An", "stock", "data_steward", date(2026, 1, 1))
    builder.add_node("stock.000002", "Vanke", "stock", "data_steward", date(2026, 1, 1))
    first_edge = builder.add_edge(
        "concept.ai",
        "stock.000001",
        "contains",
        "data_steward",
        date(2026, 1, 2),
    )
    second_edge = builder.add_edge(
        "concept.ai",
        "stock.000002",
        "contains",
        "data_steward",
        date(2026, 1, 4),
    )
    builder.verify_edge(first_edge["edge_id"], verified_by="factor_researcher", as_of_date=date(2026, 1, 3))
    builder.verify_edge(second_edge["edge_id"], verified_by="factor_researcher", as_of_date=date(2026, 1, 5))
    builder.retire_edge(first_edge["edge_id"], retired_by="risk_officer", as_of_date=date(2026, 1, 6))

    assert builder.children_as_of("concept.ai", as_of_date=date(2026, 1, 4)) == ["stock.000001"]
    assert builder.children_as_of("concept.ai", as_of_date=date(2026, 1, 5)) == [
        "stock.000001",
        "stock.000002",
    ]
    assert builder.children_as_of("concept.ai", as_of_date=date(2026, 1, 6)) == ["stock.000002"]


def test_universe_builder_rejects_empty_children_parent_id():
    builder = UniverseBuilder()

    with pytest.raises(UniverseError, match="parent_id is required"):
        builder.children_as_of(" ", as_of_date=date(2026, 1, 4))


def test_universe_builder_rejects_generic_parent_nodes():
    builder = UniverseBuilder()
    builder.add_node("concept.generic", "概念", "generic", "data_steward", date(2026, 1, 1))
    builder.add_node("stock.000001", "Ping An", "stock", "data_steward", date(2026, 1, 1))

    with pytest.raises(UniverseError, match="parent node is too generic"):
        builder.add_edge(
            "concept.generic",
            "stock.000001",
            "contains",
            "data_steward",
            date(2026, 1, 2),
        )


def test_universe_builder_rejects_synonym_duplicate_labels():
    builder = UniverseBuilder()
    builder.add_node("concept.ai", "AI 概念", "concept", "data_steward", date(2026, 1, 1))

    with pytest.raises(UniverseError, match="synonym duplicate node label"):
        builder.add_node("concept.ai_duplicate", "ai-概念", "concept", "data_steward", date(2026, 1, 2))
