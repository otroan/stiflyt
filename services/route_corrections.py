"""Per-route link exclusions + single-route validation for the signs_app
correction workflow.

ops.route_link_exclusion is a link-scoped, route-scoped correction: it drops a
link from one route's corrected graph (ops.route_link_graph) without affecting
any other route that shares the link. The signs_app UI writes these to resolve
loop/variant routes (e.g. fem30) flagged by RouteLoopValidator. See migration
020 and [[project-route-correction-design]].

CRUD goes through the operational connection (ops schema); validation goes
through the route connection (reads ops.route_link_graph + stiflyt.*).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row


def _row_to_api(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rutenummer": r["rutenummer"],
        "link_id": int(r["link_id"]),
        "reason": r.get("reason"),
        "comment": r.get("comment"),
        "reported_at": r["reported_at"].isoformat() if r.get("reported_at") else None,
        "updated_by": r.get("updated_by"),
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


def list_exclusions(op_conn, rutenummer: str) -> List[Dict[str, Any]]:
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT rutenummer, link_id, reason, comment, reported_at, updated_by, updated_at
            FROM ops.route_link_exclusion
            WHERE rutenummer = %s
            ORDER BY link_id
            """,
            (rutenummer,),
        )
        return [_row_to_api(dict(r)) for r in cur.fetchall()]


def add_exclusions(
    op_conn,
    *,
    rutenummer: str,
    link_ids: List[int],
    reason: Optional[str] = None,
    comment: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Exclude one or more links from a route. Idempotent per (rutenummer,
    link_id): re-excluding refreshes reason/comment/updated_by."""
    try:
        ids = [int(x) for x in link_ids]
    except (TypeError, ValueError):
        raise ValueError("link_ids must be integers")
    if not ids:
        raise ValueError("link_ids must be a non-empty list")
    with op_conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO ops.route_link_exclusion
                (rutenummer, link_id, reason, comment, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (rutenummer, link_id) DO UPDATE
                SET reason = EXCLUDED.reason,
                    comment = EXCLUDED.comment,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW()
            """,
            [(rutenummer, lid, reason, comment, updated_by) for lid in ids],
        )
    op_conn.commit()
    return list_exclusions(op_conn, rutenummer)


def remove_exclusions(
    op_conn,
    *,
    rutenummer: str,
    link_ids: Optional[List[int]] = None,
) -> int:
    """Remove exclusions for a route. With link_ids=None, clears all of them.
    Returns the number of rows deleted."""
    with op_conn.cursor() as cur:
        if link_ids is None:
            cur.execute(
                "DELETE FROM ops.route_link_exclusion WHERE rutenummer = %s",
                (rutenummer,),
            )
        else:
            try:
                ids = [int(x) for x in link_ids]
            except (TypeError, ValueError):
                raise ValueError("link_ids must be integers")
            if not ids:
                return 0
            cur.execute(
                "DELETE FROM ops.route_link_exclusion WHERE rutenummer = %s AND link_id = ANY(%s)",
                (rutenummer, ids),
            )
        deleted = cur.rowcount
    op_conn.commit()
    return deleted


def _arm_geometry(conn, rutenummer: str, link_ids: List[int]) -> Optional[Dict[str, Any]]:
    """GeoJSON MultiLineString (WGS84) for a loop arm's links, so the UI can
    draw the arm on the map."""
    if not link_ids:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ST_AsGeoJSON(
                       ST_Transform(
                           ST_CollectionExtract(ST_Collect(geom), 2), 4326
                       )
                   )::json
            FROM ops.route_link_graph
            WHERE rutenummer = %s AND link_id = ANY(%s)
            """,
            (rutenummer, [int(x) for x in link_ids]),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _bridge_row_to_api(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rutenummer": r["rutenummer"],
        "a_node": int(r["a_node"]),
        "b_node": int(r["b_node"]),
        "reason": r.get("reason"),
        "comment": r.get("comment"),
        "reported_at": r["reported_at"].isoformat() if r.get("reported_at") else None,
        "updated_by": r.get("updated_by"),
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


def list_bridges(op_conn, rutenummer: str) -> List[Dict[str, Any]]:
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT rutenummer, a_node, b_node, reason, comment, reported_at, updated_by, updated_at
            FROM ops.route_link_bridge
            WHERE rutenummer = %s
            ORDER BY a_node, b_node
            """,
            (rutenummer,),
        )
        return [_bridge_row_to_api(dict(r)) for r in cur.fetchall()]


def route_node_components(conn, rutenummer: str) -> Dict[int, int]:
    """node_id -> component index for the route's CURRENT corrected graph
    (exclusions + existing bridges already applied). Used to validate that a
    new bridge actually joins two different components."""
    from .route_topology import build_adjacency, components

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT link_id, a_node, b_node, length_m FROM ops.route_link_graph WHERE rutenummer = %s",
            (rutenummer,),
        )
        links = [dict(r) for r in cur.fetchall()]
    node_comp: Dict[int, int] = {}
    for i, comp in enumerate(components(build_adjacency(links))):
        for n in comp:
            node_comp[int(n)] = i
    return node_comp


def add_bridge(
    op_conn,
    *,
    rutenummer: str,
    a_node: int,
    b_node: int,
    reason: Optional[str] = None,
    comment: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Insert a bridge between two nodes of a route. Node pair is stored sorted
    (a_node < b_node) to match the table's PK/CHECK. Idempotent per pair.

    Caller must have validated the nodes are in different components (see
    route_node_components) — the DB CHECK only enforces a_node < b_node."""
    a, b = sorted((int(a_node), int(b_node)))
    if a == b:
        raise ValueError("a_node and b_node must differ")
    with op_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ops.route_link_bridge
                (rutenummer, a_node, b_node, reason, comment, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (rutenummer, a_node, b_node) DO UPDATE
                SET reason = EXCLUDED.reason,
                    comment = EXCLUDED.comment,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW()
            """,
            (rutenummer, a, b, reason, comment, updated_by),
        )
    op_conn.commit()
    return list_bridges(op_conn, rutenummer)


def remove_bridges(
    op_conn,
    *,
    rutenummer: str,
    pairs: Optional[List[tuple]] = None,
) -> int:
    """Remove bridges for a route. With pairs=None, clears all. Each pair is
    (a_node, b_node) in any order. Returns rows deleted."""
    with op_conn.cursor() as cur:
        if pairs is None:
            cur.execute("DELETE FROM ops.route_link_bridge WHERE rutenummer = %s", (rutenummer,))
            deleted = cur.rowcount
        else:
            deleted = 0
            for a_node, b_node in pairs:
                a, b = sorted((int(a_node), int(b_node)))
                cur.execute(
                    "DELETE FROM ops.route_link_bridge WHERE rutenummer = %s AND a_node = %s AND b_node = %s",
                    (rutenummer, a, b),
                )
                deleted += cur.rowcount
    op_conn.commit()
    return deleted


def validate_route(conn, rutenummer: str) -> Dict[str, Any]:
    """Run all registered validators on one route and return the result as a
    dict (status + errors/warnings/info). Mirrors the per-route logic in
    services.route_validation_report so the UI sees the same findings as the
    XLSX, including ROUTE_HAS_LOOP with its arm decomposition in metadata.

    ROUTE_HAS_LOOP arms are enriched with `geometry` (GeoJSON) so the UI can
    highlight each arm on the map for the user to pick which one to exclude.
    """
    from services.validators import get_validator_registry
    from services.route_validation_report import _load_segments_dict

    segments_dict = _load_segments_dict(conn, rutenummer)
    result = get_validator_registry().run_validators(
        {"rutenummer": rutenummer, "segments_dict": segments_dict},
        conn,
    )
    out = result.to_dict()
    for issue in out.get("errors", []):
        if issue.get("type") != "ROUTE_HAS_LOOP":
            continue
        for group in issue.get("arm_groups", []):
            for arm in group.get("arms", []):
                arm["geometry"] = _arm_geometry(conn, rutenummer, arm.get("links") or [])
    return out
