"""Multi-route junction detection for the sign pipeline.

A junction here is a graph node where >=2 distinct rutenummers meet — a
place where a hiker must make a route-choice decision. The existing
`anchor_nodes` matview already catches single-route topology branches
(degree != 2) plus ruteinfopunkt landmarks plus route-boundary anchors
(migration 010); this module surfaces the case those miss: a node whose
local link-degree happens to be 2 but where two different routes share
the node with a single link each side (T-shaped join between two routes'
endpoints).

Each junction is tagged with the set of owner areas its routes belong to
(via data/area_routes.yaml `include` overrides, falling back to the
alphabetic rutenummer prefix). A junction whose owner-area set has size
>1 is a cross-area boundary candidate per the design memo
`project-signs-cross-area-design`.

Read-only and diagnostic. No DDL, no persisted state — the
`junction_owners` registry is a follow-up.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .area_routes import owner_area_for_rutenummer
from .database import quote_identifier, validate_schema_name

FOTRUTEINFO_VIEW = "ops.fotruteinfo_patched"


def detect_multi_route_junctions(conn) -> List[Dict[str, Any]]:
    """All nodes where >=2 distinct rutenummers meet, with area tagging.

    Each row: node_id, utm_x, utm_y, lon, lat, rutenummers (list),
    route_count, owner_areas (sorted list), is_cross_area, node_degree,
    in_anchor_nodes (bool), anchor_type.
    """
    from psycopg.rows import dict_row

    schema = os.getenv("ROUTE_SCHEMA", "stiflyt")
    if not validate_schema_name(schema):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {schema}")
    schema_q = quote_identifier(schema)

    sql = f"""
        WITH node_routes AS (
            SELECT a_node AS node_id, rutenummer FROM ops.route_link_graph
            UNION ALL
            SELECT b_node AS node_id, rutenummer FROM ops.route_link_graph
        )
        SELECT
            nr.node_id,
            ST_X(n.geom)::int AS utm_x,
            ST_Y(n.geom)::int AS utm_y,
            ST_X(ST_Transform(n.geom, 4326)) AS lon,
            ST_Y(ST_Transform(n.geom, 4326)) AS lat,
            ARRAY_AGG(DISTINCT nr.rutenummer ORDER BY nr.rutenummer) AS rutenummers,
            COUNT(DISTINCT nr.rutenummer) AS route_count,
            an.degree AS node_degree,
            (an.node_id IS NOT NULL) AS in_anchor_nodes,
            an.anchor_type AS anchor_type
        FROM node_routes nr
        JOIN {schema_q}.nodes n ON n.node_id = nr.node_id
        LEFT JOIN {schema_q}.anchor_nodes an ON an.node_id = nr.node_id
        GROUP BY nr.node_id, n.geom, an.node_id, an.degree, an.anchor_type
        HAVING COUNT(DISTINCT nr.rutenummer) >= 2
        ORDER BY route_count DESC, nr.node_id
    """

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]

    for row in rows:
        owners = {
            owner_area_for_rutenummer(r) for r in (row["rutenummers"] or [])
        }
        owners.discard(None)
        row["owner_areas"] = sorted(owners)
        row["is_cross_area"] = len(owners) > 1
    return rows


def junctions_for_area(conn, area_code: str) -> List[Dict[str, Any]]:
    """Multi-route junctions where at least one route is owned by `area_code`."""
    return [
        j for j in detect_multi_route_junctions(conn)
        if area_code in j["owner_areas"]
    ]


def global_routes_for_local_nodes(
    conn, node_ids: List[int]
) -> Dict[int, List[str]]:
    """For each node_id, all distinct rutenummers touching it in the global graph.

    The per-area sign pipeline filters links to area-owned routes before
    computing the local subgraph, so a node where (say) sun27 meets sun29
    only carries sun27's links in the filtered view and looks like an
    interior point. Callers use this to surface those foreign routes back
    to the report so cross-route junctions become sign sites (see
    [[project-signs-junction-model]]).
    """
    if not node_ids:
        return {}
    from psycopg.rows import dict_row

    sql = """
        SELECT
            x.node_id,
            ARRAY_AGG(DISTINCT x.rutenummer ORDER BY x.rutenummer) AS routes
        FROM (
            SELECT a_node AS node_id, rutenummer FROM ops.route_link_graph WHERE a_node = ANY(%s)
            UNION ALL
            SELECT b_node AS node_id, rutenummer FROM ops.route_link_graph WHERE b_node = ANY(%s)
        ) x
        GROUP BY x.node_id
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (node_ids, node_ids))
        return {int(r["node_id"]): list(r["routes"] or []) for r in cur.fetchall()}
