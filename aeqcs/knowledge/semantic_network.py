"""Semantic network query helpers."""

from __future__ import annotations

from typing import Any


async def get_concept_stocks(conn: Any, node_id: str) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT child_id
        FROM semantic_edges
        WHERE parent_id=$1 AND verified AND valid_to IS NULL
        ORDER BY confidence DESC NULLS LAST
        """,
        node_id,
    )
    return [row["child_id"] for row in rows]


async def traverse_verified_tree(conn: Any, root_id: str, depth: int = 3) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        WITH RECURSIVE tree(parent_id, child_id, depth, path) AS (
          SELECT parent_id, child_id, 1, ARRAY[parent_id, child_id]
          FROM semantic_edges
          WHERE parent_id=$1 AND verified AND valid_to IS NULL
          UNION ALL
          SELECT e.parent_id, e.child_id, t.depth + 1, path || e.child_id
          FROM semantic_edges e
          JOIN tree t ON e.parent_id = t.child_id
          WHERE e.verified AND e.valid_to IS NULL AND t.depth < $2 AND NOT e.child_id = ANY(path)
        )
        SELECT * FROM tree
        """,
        root_id,
        depth,
    )
    return [dict(row) for row in rows]
