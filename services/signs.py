"""Signs report computation based on topology and anchor names."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Any

from psycopg.rows import dict_row

from .database import ROUTE_SCHEMA, validate_schema_name, quote_identifier, db_connection
from .route_endpoints import format_utm_shortform
from .route_service import (
    get_routes_from_view,
    get_route_links,
    get_route_endpoint_nodes_and_length,
    point_route_km,
    wgs84_to_utm_display,
)
from .operational_database import op_db_connection
from .operational_store import (
    get_endpoint_names_for_anchors,
    get_endpoint_names_for_anchor_routes,
    get_sign_site_destinations_bulk,
    get_sign_site_skilt_for_sites,
    get_sign_sites_for_route,
    DEFAULT_BACK_TEXT,
)

# Match sign_site to sign by (rutenummer, route_km); anchor_node_id is not used (robust to DB refresh).
ROUTE_KM_TOLERANCE_KM = 0.01  # 10 m


def _serialize_sign_skilt_for_api(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": row.get("id"),
        "direction": row.get("direction"),
        "status": row.get("status"),
        "skiltfarge": row.get("skiltfarge"),
        "distance_meters": row.get("distance_meters"),
    }
    ua = row.get("updated_at")
    if ua is not None and hasattr(ua, "isoformat"):
        out["updated_at"] = ua.isoformat()
    return out


def _empty_sign_skilt() -> Dict[str, Any]:
    return {"id": None, "direction": None, "status": None, "skiltfarge": None, "distance_meters": None}


def _merge_sign_skilt_into_report_signs(signs: List[Dict[str, Any]]) -> None:
    """Attach per-destination skilt (retning, status, farge, km) for signs with sign_site_id."""
    site_ids = sorted({int(s["sign_site_id"]) for s in signs if s.get("sign_site_id") is not None})
    if not site_ids:
        return
    with op_db_connection() as op_conn:
        by_site = get_sign_site_skilt_for_sites(op_conn, site_ids)
    for sign in signs:
        sid = sign.get("sign_site_id")
        if sid is None:
            continue
        sign["status"] = []
        by_anchor = by_site.get(int(sid), {})
        for d in sign.get("destinations") or []:
            aid = d.get("anchor_node_id")
            if aid is None:
                continue
            row = by_anchor.get(int(aid))
            if row:
                d["skilt"] = _serialize_sign_skilt_for_api(row)
            else:
                d["skilt"] = _empty_sign_skilt()


def _resolve_custom_destinations(
    anchor_list: List[Dict],
    route_km: Optional[float],
    ep: Optional[Dict],
    names: Dict[int, Dict],
) -> List[Dict]:
    """Build destination list with name and distance_meters from custom anchor list."""
    if not anchor_list or route_km is None or not ep:
        result = []
        for d in anchor_list:
            aid = d.get("anchor_node_id")
            if aid is None:
                continue
            name = (names.get(aid) or {}).get("name") or (f"Anchor {aid}" if aid else "")
            result.append({"anchor_node_id": aid, "name": name, "distance_meters": None})
        return result if result else []
    length_m = float(ep.get("length_m") or 0)
    first_id = ep.get("first_a_node")
    last_id = ep.get("last_b_node")
    dist_to_start_m = route_km * 1000.0
    dist_to_end_m = length_m - dist_to_start_m
    result = []
    for d in anchor_list:
        aid = d.get("anchor_node_id")
        if aid is None:
            continue
        name = (names.get(aid) or {}).get("name") or (f"Anchor {aid}" if aid else "")
        if aid == first_id:
            dist = round(dist_to_start_m, 0)
        elif aid == last_id:
            dist = round(dist_to_end_m, 0)
        else:
            dist = None
        result.append({"anchor_node_id": aid, "name": name, "distance_meters": dist})
    return result


def _match_sign_site_by_location(
    sign_sites: List[Dict],
    rutenummer: Optional[str],
    route_km: Optional[float],
) -> Optional[Dict]:
    """Find a sign_site matching (rutenummer, route_km). Uses tolerance for route_km."""
    if rutenummer is None or route_km is None or not sign_sites:
        return None
    for site in sign_sites:
        if site.get("rutenummer") != rutenummer:
            continue
        skm = site.get("route_km")
        if skm is None:
            continue
        if abs(float(skm) - float(route_km)) < ROUTE_KM_TOLERANCE_KM:
            return site
    return None


def _build_graph(links: List[Dict[str, Any]]) -> Tuple[Dict[int, List[Tuple[int, float]]], Dict[int, int]]:
    adjacency: Dict[int, List[Tuple[int, float]]] = {}
    degrees: Dict[int, int] = {}

    for link in links:
        a_node = link.get("a_node")
        b_node = link.get("b_node")
        if a_node is None or b_node is None:
            continue
        try:
            a_node = int(a_node)
            b_node = int(b_node)
        except (TypeError, ValueError):
            continue

        length = link.get("length_m")
        if length is None:
            length = link.get("length_meters")
        length_val = float(length) if length is not None else 0.0

        adjacency.setdefault(a_node, []).append((b_node, length_val))
        adjacency.setdefault(b_node, []).append((a_node, length_val))
        degrees[a_node] = degrees.get(a_node, 0) + 1
        degrees[b_node] = degrees.get(b_node, 0) + 1

    return adjacency, degrees


def _calculate_route_distance(
    route_links: List[Dict[str, Any]],
    from_endpoint: int,
    to_endpoint: int,
) -> Optional[float]:
    """
    Calculate distance along a route from one endpoint to another.
    Returns None if endpoints are not connected via this route.
    """
    if not route_links:
        return None
    
    # Build adjacency list for this route only
    route_adjacency: Dict[int, List[Tuple[int, float]]] = {}
    for link in route_links:
        a_node = link.get("a_node")
        b_node = link.get("b_node")
        length = link.get("length_m") or link.get("length_meters") or 0.0
        
        if a_node is None or b_node is None:
            continue
        try:
            a_node = int(a_node)
            b_node = int(b_node)
            length_val = float(length)
        except (TypeError, ValueError):
            continue
        
        route_adjacency.setdefault(a_node, []).append((b_node, length_val))
        route_adjacency.setdefault(b_node, []).append((a_node, length_val))
    
    # Use BFS or simple path finding to traverse from from_endpoint to to_endpoint
    # Since routes are typically linear (or have known structure), we can traverse
    visited = set()
    queue: List[Tuple[int, float]] = [(from_endpoint, 0.0)]
    
    while queue:
        current_node, current_dist = queue.pop(0)
        if current_node == to_endpoint:
            return current_dist
        
        if current_node in visited:
            continue
        visited.add(current_node)
        
        for neighbor, link_length in route_adjacency.get(current_node, []):
            if neighbor not in visited:
                queue.append((neighbor, current_dist + link_length))
    
    return None


def _cumulative_km_along_route(
    route_links: List[Dict[str, Any]],
    endpoint_set: set,
) -> Dict[int, float]:
    """
    For each node on the route, return cumulative distance from one endpoint in km.
    Uses BFS from one endpoint; values are in km (round to 4 decimals).
    """
    if not route_links or len(endpoint_set) < 2:
        return {}
    route_adjacency: Dict[int, List[Tuple[int, float]]] = {}
    for link in route_links:
        a_node = link.get("a_node")
        b_node = link.get("b_node")
        length = link.get("length_m") or link.get("length_meters") or 0.0
        if a_node is None or b_node is None:
            continue
        try:
            a_node = int(a_node)
            b_node = int(b_node)
            length_val = float(length)
        except (TypeError, ValueError):
            continue
        route_adjacency.setdefault(a_node, []).append((b_node, length_val))
        route_adjacency.setdefault(b_node, []).append((a_node, length_val))
    endpoints = sorted(endpoint_set)
    start = endpoints[0]
    visited: set = set()
    queue: List[Tuple[int, float]] = [(start, 0.0)]
    out: Dict[int, float] = {}
    while queue:
        current_node, current_m = queue.pop(0)
        if current_node in visited:
            continue
        visited.add(current_node)
        out[current_node] = round(current_m / 1000.0, 4)
        for neighbor, link_m in route_adjacency.get(current_node, []):
            if neighbor not in visited:
                queue.append((neighbor, current_m + link_m))
    return out


def _fetch_anchor_nodes(conn, anchor_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not anchor_ids:
        return {}

    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    # Check if navn column exists in anchor_nodes
    schema_quoted = quote_identifier(ROUTE_SCHEMA)
    has_navn_column = False
    with conn.cursor() as check_cur:
        check_cur.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'anchor_nodes'
                  AND column_name = 'navn'
            )
        """, (ROUTE_SCHEMA,))
        has_navn_column = check_cur.fetchone()[0]

    # Build SELECT clause conditionally
    navn_select = "navn" if has_navn_column else "NULL as navn"

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                node_id,
                ST_X(ST_Transform(geom, 4326)) as lon,
                ST_Y(ST_Transform(geom, 4326)) as lat,
                {navn_select}
            FROM {schema_quoted}.anchor_nodes
            WHERE node_id = ANY(%s);
            """,
            (anchor_ids,),
        )
        rows = cur.fetchall()

    results: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        node_id = row.get("node_id")
        if node_id is None:
            continue
        try:
            node_id = int(node_id)
        except (TypeError, ValueError):
            continue
        results[node_id] = {
            "lon": float(row["lon"]) if row.get("lon") is not None else None,
            "lat": float(row["lat"]) if row.get("lat") is not None else None,
            "name": row.get("navn"),
        }
    return results


def _resolve_anchor_names_for_route(
    conn,
    anchor_nodes: Dict[int, Dict[str, Any]],
    anchor_ids: List[int],
    rutenummer: str,
) -> Dict[int, Dict[str, Any]]:
    resolved: Dict[int, Dict[str, Any]] = {}
    with op_db_connection() as op_conn:
        overrides = get_endpoint_names_for_anchors(op_conn, anchor_ids, rutenummer=rutenummer)

    for anchor_id in anchor_ids:
        override = overrides.get(anchor_id)
        if override and override.get("name"):
            resolved[anchor_id] = {
                "name": override.get("name"),
                "source_type": override.get("source_type"),
                "source_id": override.get("source_id"),
                "distance_meters": override.get("distance_meters"),
                "is_validated": True,
            }
            continue
        
        # Use anchor_nodes.name if present (no extra lookups; names are already given elsewhere)
        anchor_node = anchor_nodes.get(anchor_id, {})
        anchor_name = anchor_node.get("name")
        if anchor_name:
            resolved[anchor_id] = {
                "name": format_utm_shortform(anchor_name),
                "source_type": "anchor_node",
                "source_id": None,
                "distance_meters": None,
                "is_validated": False,
            }
            continue
        
        # No name from ops or anchor_node; use simple fallback without DB lookup
        resolved[anchor_id] = {
            "name": f"Anchor {anchor_id}",
            "source_type": "fallback",
            "source_id": None,
            "distance_meters": None,
            "is_validated": False,
        }
    return resolved


def _resolve_anchor_names_for_prefix(
    conn,
    anchor_nodes: Dict[int, Dict[str, Any]],
    anchor_ids: List[int],
    rutenummer_list: List[str],
) -> Dict[int, Dict[str, Any]]:
    resolved: Dict[int, Dict[str, Any]] = {}
    overrides_by_route: Dict[str, Dict[int, Dict[str, Any]]] = {}

    if rutenummer_list:
        with op_db_connection() as op_conn:
            overrides_by_route = get_endpoint_names_for_anchor_routes(
                op_conn,
                anchor_ids,
                rutenummer_list,
            )

    for anchor_id in anchor_ids:
        found_override = None
        for rute in rutenummer_list:
            override = overrides_by_route.get(rute, {}).get(anchor_id)
            if override and override.get("name"):
                found_override = override
                break
        if found_override:
            resolved[anchor_id] = {
                "name": found_override.get("name"),
                "source_type": found_override.get("source_type"),
                "source_id": found_override.get("source_id"),
                "distance_meters": found_override.get("distance_meters"),
                "is_validated": True,
            }
            continue
        
        # Use anchor_nodes.name if present (no extra lookups; names are already given elsewhere)
        anchor_node = anchor_nodes.get(anchor_id, {})
        anchor_name = anchor_node.get("name")
        if anchor_name:
            resolved[anchor_id] = {
                "name": format_utm_shortform(anchor_name),
                "source_type": "anchor_node",
                "source_id": None,
                "distance_meters": None,
                "is_validated": False,
            }
            continue
        
        # No name from ops or anchor_node; use simple fallback without DB lookup
        resolved[anchor_id] = {
            "name": f"Anchor {anchor_id}",
            "source_type": "fallback",
            "source_id": None,
            "distance_meters": None,
            "is_validated": False,
        }
    return resolved


def compute_sign_report_from_links(
    links: List[Dict[str, Any]],
    anchor_nodes: Dict[int, Dict[str, Any]],
    anchor_names: Dict[int, Dict[str, Any]],
    sign_status: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    extra_junction_nodes: Optional[set] = None,
    foreign_routes_by_node: Optional[Dict[int, List[str]]] = None,
) -> Dict[str, Any]:
    adjacency, degrees = _build_graph(links)
    
    # Build mapping of node -> set of routes that pass through it
    node_routes: Dict[int, set] = {}
    route_links: Dict[str, List[Dict[str, Any]]] = {}  # route -> list of links
    route_endpoints: Dict[str, set] = {}  # route -> set of endpoints (per route)
    
    for link in links:
        rutenummer_list = link.get("rutenummer_list")
        if not rutenummer_list:
            continue
        
        route_set = set(rutenummer_list) if isinstance(rutenummer_list, list) else set()
        
        a_node = link.get("a_node")
        b_node = link.get("b_node")
        a_node_int = None
        b_node_int = None
        
        if a_node is not None:
            try:
                a_node_int = int(a_node)
                node_routes.setdefault(a_node_int, set()).update(route_set)
            except (TypeError, ValueError):
                pass
        if b_node is not None:
            try:
                b_node_int = int(b_node)
                node_routes.setdefault(b_node_int, set()).update(route_set)
            except (TypeError, ValueError):
                pass
        
        # Build route -> links mapping
        for route in route_set:
            route_links.setdefault(route, []).append(link)
    
    # Identify route endpoints: for each route, find first and last nodes
    # (nodes that appear only once in the route's link sequence)
    all_route_endpoints: set = set()  # All nodes that are endpoints of at least one route
    endpoint_routes: Dict[int, set] = {}  # endpoint -> routes it belongs to
    
    for route, route_link_list in route_links.items():
        if not route_link_list:
            continue
        
        # Count node occurrences in this route
        node_counts: Dict[int, int] = {}
        for link in route_link_list:
            a_node = link.get("a_node")
            b_node = link.get("b_node")
            if a_node is not None:
                try:
                    a_node_int = int(a_node)
                    node_counts[a_node_int] = node_counts.get(a_node_int, 0) + 1
                except (TypeError, ValueError):
                    pass
            if b_node is not None:
                try:
                    b_node_int = int(b_node)
                    node_counts[b_node_int] = node_counts.get(b_node_int, 0) + 1
                except (TypeError, ValueError):
                    pass
        
        # Nodes that appear only once are endpoints of this route
        route_endpoint_set = {node for node, count in node_counts.items() if count == 1}
        route_endpoints[route] = route_endpoint_set
        all_route_endpoints.update(route_endpoint_set)
        
        # Track which routes each endpoint belongs to
        for endpoint in route_endpoint_set:
            endpoint_routes.setdefault(endpoint, set()).add(route)
    
    # Identify sign nodes:
    # 1. Nodes that are endpoints of at least one route (regardless of degree)
    # 2. Junctions (nodes with degree >= 3)
    endpoints_list = sorted(all_route_endpoints)
    endpoints_set = all_route_endpoints  # For fast lookup
    local_junctions = {node for node, degree in degrees.items() if degree >= 3}
    # Cross-route junctions where the foreign-route links were stripped by
    # the area filter — local degree looks like 2, but globally the node
    # carries another route. Caller supplies these from junctions module.
    extra = set(extra_junction_nodes or ())
    junctions = sorted(local_junctions | extra)
    junctions_set = set(junctions)
    sign_nodes = sorted(set(endpoints_list) | junctions_set)

    # Cumulative km from route start at each node (from link lengths, no geometry)
    cumulative_km_per_route: Dict[str, Dict[int, float]] = {}
    for route, link_list in route_links.items():
        ep_set = route_endpoints.get(route, set())
        if len(ep_set) >= 2:
            cumulative_km_per_route[route] = _cumulative_km_along_route(link_list, ep_set)

    signs: List[Dict[str, Any]] = []
    missing_signs: List[Dict[str, Any]] = []
    missing_destinations: List[Dict[str, Any]] = []
    missing_anchor_names: List[Dict[str, Any]] = []

    for sign_node in sign_nodes:
        is_junction = sign_node in junctions
        sign_destinations = []
        
        if is_junction:
            # All endpoints of every route that passes through this junction, with distance along that route.
            junction_routes = node_routes.get(sign_node, set())
            for route in junction_routes:
                route_link_list = route_links.get(route, [])
                if not route_link_list:
                    continue
                route_endpoint_set = route_endpoints.get(route, set())
                for other_endpoint_id in route_endpoint_set:
                    if other_endpoint_id == sign_node:
                        continue
                    route_distance = _calculate_route_distance(
                        route_link_list,
                        sign_node,
                        other_endpoint_id,
                    )
                    if route_distance is None:
                        continue
                    name_info = anchor_names.get(other_endpoint_id)
                    if name_info and name_info.get("name"):
                        destination_name = name_info["name"]
                    else:
                        other_anchor = anchor_nodes.get(other_endpoint_id, {})
                        other_anchor_name = other_anchor.get("name")
                        if other_anchor_name:
                            destination_name = format_utm_shortform(other_anchor_name)
                        else:
                            destination_name = f"Anchor {other_endpoint_id}"
                    existing_dest = next(
                        (d for d in sign_destinations if d["anchor_node_id"] == other_endpoint_id),
                        None,
                    )
                    rd = float(route_distance)
                    if existing_dest:
                        if rd < existing_dest["distance_meters"]:
                            existing_dest["distance_meters"] = rd
                            existing_dest["name"] = destination_name
                    else:
                        sign_destinations.append(
                            {
                                "anchor_node_id": other_endpoint_id,
                                "name": destination_name,
                                "distance_meters": rd,
                            }
                        )
        else:
            # For endpoints, show destinations along each route the endpoint belongs to
            endpoint_route_set = endpoint_routes.get(sign_node, set())
            
            for route in endpoint_route_set:
                # Find the other endpoint(s) of this route
                route_endpoint_set = route_endpoints.get(route, set())
                other_endpoints = route_endpoint_set - {sign_node}
                
                if not other_endpoints:
                    continue
                
                # Get links for this route
                route_link_list = route_links.get(route, [])
                if not route_link_list:
                    continue
                
                # For each other endpoint, calculate distance along the route
                for other_endpoint_id in other_endpoints:
                    # Calculate distance along the route first
                    route_distance = _calculate_route_distance(
                        route_link_list,
                        sign_node,
                        other_endpoint_id,
                    )
                    
                    if route_distance is None:
                        continue
                    
                    # Get name info (may be None if no name resolved)
                    name_info = anchor_names.get(other_endpoint_id)
                    destination_name = None
                    if name_info and name_info.get("name"):
                        destination_name = name_info["name"]
                    else:
                        # Fallback: use anchor node name or format as "Anchor {id}"
                        other_anchor = anchor_nodes.get(other_endpoint_id, {})
                        other_anchor_name = other_anchor.get("name")
                        if other_anchor_name:
                            destination_name = format_utm_shortform(other_anchor_name)
                        else:
                            destination_name = f"Anchor {other_endpoint_id}"
                    
                    # Check if we already added this destination (from another route)
                    existing_dest = next(
                        (d for d in sign_destinations if d["anchor_node_id"] == other_endpoint_id),
                        None,
                    )
                    
                    if existing_dest:
                        # If this route is shorter, update the distance
                        if route_distance < existing_dest["distance_meters"]:
                            existing_dest["distance_meters"] = float(route_distance)
                    else:
                        sign_destinations.append(
                            {
                                "anchor_node_id": other_endpoint_id,
                                "name": destination_name,
                                "distance_meters": float(route_distance),
                            }
                        )

        anchor_info = anchor_nodes.get(sign_node, {})
        status_rows = sign_status.get(sign_node, []) if sign_status else []
        serialized_status = []
        for row in status_rows:
            last_inspected = row.get("last_inspected")
            updated_at = row.get("updated_at")
            serialized = {
                **row,
                "last_inspected": last_inspected.isoformat() if hasattr(last_inspected, "isoformat") else last_inspected,
                "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
            }
            serialized_status.append(serialized)

        sign_foreign = sorted(
            (foreign_routes_by_node or {}).get(sign_node, []) or []
        )
        signs.append(
            {
                "anchor_node_id": sign_node,
                "coordinates": [
                    anchor_info.get("lon"),
                    anchor_info.get("lat"),
                ],
                "link_count": degrees.get(sign_node, 0),
                "is_endpoint": sign_node in endpoints_set,
                "is_junction": sign_node in junctions_set,
                "name": anchor_names.get(sign_node, {}).get("name"),
                "destinations": sign_destinations,
                "status": serialized_status,
                "rutenummer_list": sorted(node_routes.get(sign_node, set())),
                "route_km_by_route": {
                    r: cumulative_km_per_route[r][sign_node]
                    for r in node_routes.get(sign_node, set())
                    if r in cumulative_km_per_route and sign_node in cumulative_km_per_route[r]
                },
                "foreign_route_numbers": sign_foreign,
                "is_cross_area": bool(sign_foreign),
            }
        )

        if not sign_destinations:
            missing_signs.append(
                {
                    "anchor_node_id": sign_node,
                    "coordinates": [
                        anchor_info.get("lon"),
                        anchor_info.get("lat"),
                    ],
                    "reason": "no_destinations",
                }
            )
            missing_destinations.append(
                {
                    "anchor_node_id": sign_node,
                    "coordinates": [
                        anchor_info.get("lon"),
                        anchor_info.get("lat"),
                    ],
                    "reason": "no_destinations",
                }
            )

        if not anchor_names.get(sign_node, {}).get("name"):
            missing_anchor_names.append(
                {
                    "anchor_node_id": sign_node,
                    "coordinates": [
                        anchor_info.get("lon"),
                        anchor_info.get("lat"),
                    ],
                    "reason": "missing_anchor_name",
                }
            )

    # Count unique destinations across all signs
    all_destination_ids = set()
    for sign in signs:
        for dest in sign.get("destinations", []):
            all_destination_ids.add(dest.get("anchor_node_id"))
    
    return {
        "signs": signs,
        "missing": {
            "missing_signs": missing_signs,
            "missing_destinations": missing_destinations,
            "missing_anchor_names": missing_anchor_names,
        },
        "totals": {
            "sign_count": len(signs),
            "endpoint_count": len(endpoints_list),
            "junction_count": len(junctions),
            "destination_count": len(all_destination_ids),
        },
    }


def _get_links_for_route_nodes(conn, rutenummer: str) -> List[Dict[str, Any]]:
    """Get all links connected to nodes on a route (including links from other routes at junctions)."""
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")
    
    schema_quoted = quote_identifier(ROUTE_SCHEMA)
    
    with conn.cursor(row_factory=dict_row) as cur:
        # First, get all nodes on the route
        cur.execute(
            f"""
            SELECT DISTINCT node_id
            FROM (
                SELECT a_node as node_id
                FROM {schema_quoted}.links_with_routes
                WHERE %s = ANY(rutenummer_list)
                UNION
                SELECT b_node as node_id
                FROM {schema_quoted}.links_with_routes
                WHERE %s = ANY(rutenummer_list)
            ) nodes;
            """,
            (rutenummer, rutenummer),
        )
        route_nodes = [row["node_id"] for row in cur.fetchall()]
        
        if not route_nodes:
            return []
        
        # Then get all links connected to those nodes (from any route)
        cur.execute(
            f"""
            SELECT DISTINCT
                l.link_id,
                l.a_node,
                l.b_node,
                l.length_m,
                l.rutenummer_list
            FROM {schema_quoted}.links_with_routes l
            WHERE l.a_node = ANY(%s) OR l.b_node = ANY(%s)
            ORDER BY l.link_id;
            """,
            (route_nodes, route_nodes),
        )
        rows = cur.fetchall()
    
    return [dict(row) for row in rows]


def _enrich_signs_with_sign_sites_and_route_km(
    conn,
    rutenummer: str,
    report: Dict[str, Any],
) -> None:
    """Enrich report: match sign_sites by (rutenummer, route_km); per-destination skilt from sign_site_skilt. Add custom sign sites (no anchor)."""
    with op_db_connection() as op_conn:
        all_sites = get_sign_sites_for_route(op_conn, rutenummer)
        custom_sites = [s for s in all_sites if s.get("anchor_node_id") is None]

    matched_site_ids: List[int] = []
    for sign in report["signs"]:
        coords = sign.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        # Use precomputed route_km from link topology when available (no DB/geometry)
        route_km = (sign.get("route_km_by_route") or {}).get(rutenummer)
        if route_km is None and lon is not None and lat is not None:
            route_km = point_route_km(conn, rutenummer, lon, lat)
        sign["route_km"] = route_km
        site = _match_sign_site_by_location(all_sites, rutenummer, route_km)
        if site:
            matched_site_ids.append(site["id"])
        sign["_matched_site"] = site  # temporary for collecting ids

    for sign in report["signs"]:
        site = sign.pop("_matched_site", None)
        sign.pop("route_km_by_route", None)  # internal only, not in API response
        aid = sign.get("anchor_node_id")
        coords = sign.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]

        if site:
            sign["sign_site_id"] = site["id"]
            sign["route_km"] = site.get("route_km")
            sign["back_text"] = site.get("back_text") or DEFAULT_BACK_TEXT
            sign["send_to_name"] = site.get("send_to_name")
            sign["send_to_address"] = site.get("send_to_address")
            sign["skiltfarge"] = site.get("skiltfarge")
            sign["status"] = []
        else:
            sign["sign_site_id"] = None
            sign["back_text"] = DEFAULT_BACK_TEXT
            sign["send_to_name"] = None
            sign["send_to_address"] = None
            sign["skiltfarge"] = None
            sign["status"] = []

        sign["skiltstedidentifikator"] = str(site["id"]) if site else f"{rutenummer}-{aid}"
        if lon is not None and lat is not None:
            sign["utm_coords"] = wgs84_to_utm_display(lon, lat)
        else:
            sign["utm_coords"] = None

    all_site_ids = list(set(matched_site_ids) | {s["id"] for s in custom_sites})
    ep_main = get_route_endpoint_nodes_and_length(conn, rutenummer) if rutenummer else None

    # Default destinations for custom sign sites: both route endpoints with distance. Load custom overrides.
    route_ep_cache: Dict[str, Dict] = {}
    custom_destinations_by_site: Dict[int, List[Dict]] = {}
    with op_db_connection() as op_conn:
        custom_destinations_by_site = get_sign_site_destinations_bulk(op_conn, all_site_ids) if all_site_ids else {}
        anchor_ids_custom = set()
        for dests in custom_destinations_by_site.values():
            for d in dests:
                anchor_ids_custom.add(d.get("anchor_node_id"))
        anchor_ids_custom.discard(None)
        names_custom = get_endpoint_names_for_anchors(op_conn, list(anchor_ids_custom), rutenummer=rutenummer) if anchor_ids_custom and rutenummer else {}
        for site in custom_sites:
            rnum = site.get("rutenummer")
            if rnum not in route_ep_cache and rnum:
                ep = get_route_endpoint_nodes_and_length(conn, rnum)
                if ep:
                    names = get_endpoint_names_for_anchors(op_conn, [ep["first_a_node"], ep["last_b_node"]], rutenummer=rnum) if (ep.get("first_a_node") is not None or ep.get("last_b_node") is not None) else {}
                    route_ep_cache[rnum] = {**ep, "names": names}
                else:
                    route_ep_cache[rnum] = {}
            elif not rnum:
                route_ep_cache[rnum] = {}

    for sign in report["signs"]:
        sid = sign.get("sign_site_id")
        if sid is not None and sid in custom_destinations_by_site and ep_main:
            sign["destinations"] = _resolve_custom_destinations(
                custom_destinations_by_site[sid],
                sign.get("route_km"),
                ep_main,
                names_custom,
            )

    for site in custom_sites:
        lon, lat = site.get("lon"), site.get("lat")
        destinations = []
        rnum = site.get("rutenummer")
        route_km_val = site.get("route_km")
        if site["id"] in custom_destinations_by_site:
            ep_info = route_ep_cache.get(rnum, {}) if rnum else {}
            names_site = (ep_info.get("names") or {}) if ep_info else names_custom
            destinations = _resolve_custom_destinations(
                custom_destinations_by_site[site["id"]],
                route_km_val,
                ep_info or None,
                names_site,
            )
        else:
            ep_info = route_ep_cache.get(rnum, {}) if rnum else {}
            if ep_info and route_km_val is not None and ep_info.get("length_m") is not None:
                length_m = float(ep_info["length_m"])
                first_id = ep_info.get("first_a_node")
                last_id = ep_info.get("last_b_node")
                names = ep_info.get("names") or {}
                dist_to_start_m = route_km_val * 1000.0
                dist_to_end_m = length_m - dist_to_start_m
                if first_id is not None:
                    name = (names.get(first_id) or {}).get("name") or (f"Anchor {first_id}" if first_id else "")
                    destinations.append({"anchor_node_id": first_id, "name": name, "distance_meters": round(dist_to_start_m, 0)})
                if last_id is not None and last_id != first_id:
                    name = (names.get(last_id) or {}).get("name") or (f"Anchor {last_id}" if last_id else "")
                    destinations.append({"anchor_node_id": last_id, "name": name, "distance_meters": round(dist_to_end_m, 0)})
        report["signs"].append({
            "anchor_node_id": None,
            "sign_site_id": site["id"],
            "skiltstedidentifikator": str(site["id"]),
            "coordinates": [lon, lat],
            "link_count": 0,
            "is_endpoint": False,
            "is_junction": False,
            "name": site.get("name"),
            "destinations": destinations,
            "status": [],
            "route_km": site.get("route_km"),
            "back_text": site.get("back_text") or DEFAULT_BACK_TEXT,
            "send_to_name": site.get("send_to_name"),
            "send_to_address": site.get("send_to_address"),
            "skiltfarge": site.get("skiltfarge"),
            "utm_coords": wgs84_to_utm_display(lon, lat) if (lon is not None and lat is not None) else None,
            "rutenummer_list": [site.get("rutenummer")] if site.get("rutenummer") else [],
        })
    _merge_sign_skilt_into_report_signs(report["signs"])
    report["totals"]["sign_count"] = len(report["signs"])


def _enrich_signs_with_sign_sites_and_route_km_multi(conn, report: Dict[str, Any]) -> None:
    """Enrich report (prefix/bbox): match sign_sites by (rutenummer, route_km); status only from sign_sites. Add custom sign sites."""
    routes = report.get("scope", {}).get("routes") or []
    sign_list = report["signs"]
    with op_db_connection() as op_conn:
        all_sites_flat: List[Dict] = []
        seen_site_ids = set()
        for r in routes:
            for s in get_sign_sites_for_route(op_conn, r):
                if s["id"] not in seen_site_ids:
                    seen_site_ids.add(s["id"])
                    all_sites_flat.append(s)
        custom_sites = [s for s in all_sites_flat if s.get("anchor_node_id") is None]

    matched_site_ids: List[int] = []
    for sign in sign_list:
        coords = sign.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        rutenummer_list = sign.get("rutenummer_list") or []
        route_for_km = rutenummer_list[0] if rutenummer_list else None
        # Use precomputed route_km from link topology when available (no DB/geometry)
        route_km = (sign.get("route_km_by_route") or {}).get(route_for_km) if route_for_km else None
        if route_km is None and route_for_km and lon is not None and lat is not None:
            route_km = point_route_km(conn, route_for_km, lon, lat)
        sign["route_km"] = route_km
        site = _match_sign_site_by_location(all_sites_flat, route_for_km, route_km)
        if site:
            matched_site_ids.append(site["id"])
        sign["_matched_site"] = site

    for sign in sign_list:
        site = sign.pop("_matched_site", None)
        sign.pop("route_km_by_route", None)  # internal only, not in API response
        aid = sign.get("anchor_node_id")
        coords = sign.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        rutenummer_list = sign.get("rutenummer_list") or []
        route_for_km = rutenummer_list[0] if rutenummer_list else None

        if site:
            sign["sign_site_id"] = site["id"]
            sign["route_km"] = site.get("route_km")
            sign["back_text"] = site.get("back_text") or DEFAULT_BACK_TEXT
            sign["send_to_name"] = site.get("send_to_name")
            sign["send_to_address"] = site.get("send_to_address")
            sign["skiltfarge"] = site.get("skiltfarge")
            sign["status"] = []
        else:
            sign["sign_site_id"] = None
            sign["back_text"] = DEFAULT_BACK_TEXT
            sign["send_to_name"] = None
            sign["send_to_address"] = None
            sign["skiltfarge"] = None
            sign["status"] = []

        sign["skiltstedidentifikator"] = str(site["id"]) if site else (f"{route_for_km}-{aid}" if route_for_km and aid is not None else str(aid) if aid is not None else "?")
        if lon is not None and lat is not None:
            sign["utm_coords"] = wgs84_to_utm_display(lon, lat)
        else:
            sign["utm_coords"] = None

    all_site_ids_multi = list(set(matched_site_ids) | {s["id"] for s in custom_sites})
    route_ep_cache_multi: Dict[str, Dict] = {}
    custom_destinations_by_site_multi: Dict[int, List[Dict]] = {}
    names_by_route_multi: Dict[str, Dict[int, Dict]] = {}
    with op_db_connection() as op_conn:
        custom_destinations_by_site_multi = get_sign_site_destinations_bulk(op_conn, all_site_ids_multi) if all_site_ids_multi else {}
        anchor_ids_custom_multi = set()
        for dests in custom_destinations_by_site_multi.values():
            for d in dests:
                anchor_ids_custom_multi.add(d.get("anchor_node_id"))
        anchor_ids_custom_multi.discard(None)
        if anchor_ids_custom_multi and routes:
            names_by_route_multi = get_endpoint_names_for_anchor_routes(op_conn, list(anchor_ids_custom_multi), routes)
        for rnum in routes:
            if rnum and rnum not in route_ep_cache_multi:
                ep = get_route_endpoint_nodes_and_length(conn, rnum)
                if ep:
                    names = get_endpoint_names_for_anchors(op_conn, [ep["first_a_node"], ep["last_b_node"]], rutenummer=rnum) if (ep.get("first_a_node") is not None or ep.get("last_b_node") is not None) else {}
                    route_ep_cache_multi[rnum] = {**ep, "names": names}
                else:
                    route_ep_cache_multi[rnum] = {}

    for sign in sign_list:
        sid = sign.get("sign_site_id")
        if sid is not None and sid in custom_destinations_by_site_multi:
            route_for_km = (sign.get("rutenummer_list") or [None])[0]
            ep = route_ep_cache_multi.get(route_for_km, {}) if route_for_km else {}
            names = names_by_route_multi.get(route_for_km, {}) if route_for_km else (ep.get("names") or {})
            sign["destinations"] = _resolve_custom_destinations(
                custom_destinations_by_site_multi[sid],
                sign.get("route_km"),
                ep or None,
                names,
            )

    for site in custom_sites:
        lon, lat = site.get("lon"), site.get("lat")
        destinations = []
        rnum = site.get("rutenummer")
        route_km_val = site.get("route_km")
        if site["id"] in custom_destinations_by_site_multi:
            ep_info = route_ep_cache_multi.get(rnum, {}) if rnum else {}
            names_site = (ep_info.get("names") or {}) if ep_info else names_by_route_multi.get(rnum, {})
            destinations = _resolve_custom_destinations(
                custom_destinations_by_site_multi[site["id"]],
                route_km_val,
                ep_info or None,
                names_site,
            )
        else:
            ep_info = route_ep_cache_multi.get(rnum, {}) if rnum else {}
            if ep_info and route_km_val is not None and ep_info.get("length_m") is not None:
                length_m = float(ep_info["length_m"])
                first_id = ep_info.get("first_a_node")
                last_id = ep_info.get("last_b_node")
                names = ep_info.get("names") or {}
                dist_to_start_m = route_km_val * 1000.0
                dist_to_end_m = length_m - dist_to_start_m
                if first_id is not None:
                    name = (names.get(first_id) or {}).get("name") or (f"Anchor {first_id}" if first_id else "")
                    destinations.append({"anchor_node_id": first_id, "name": name, "distance_meters": round(dist_to_start_m, 0)})
                if last_id is not None and last_id != first_id:
                    name = (names.get(last_id) or {}).get("name") or (f"Anchor {last_id}" if last_id else "")
                    destinations.append({"anchor_node_id": last_id, "name": name, "distance_meters": round(dist_to_end_m, 0)})
        report["signs"].append({
            "anchor_node_id": None,
            "sign_site_id": site["id"],
            "skiltstedidentifikator": str(site["id"]),
            "coordinates": [lon, lat],
            "link_count": 0,
            "is_endpoint": False,
            "is_junction": False,
            "name": site.get("name"),
            "destinations": destinations,
            "status": [],
            "route_km": site.get("route_km"),
            "back_text": site.get("back_text") or DEFAULT_BACK_TEXT,
            "send_to_name": site.get("send_to_name"),
            "send_to_address": site.get("send_to_address"),
            "skiltfarge": site.get("skiltfarge"),
            "utm_coords": wgs84_to_utm_display(lon, lat) if (lon is not None and lat is not None) else None,
            "rutenummer_list": [site["rutenummer"]] if site.get("rutenummer") else [],
        })
    _merge_sign_skilt_into_report_signs(report["signs"])
    report["totals"]["sign_count"] = len(report["signs"])


def get_signs_for_route(conn, rutenummer: str) -> Dict[str, Any]:
    # Get all links connected to nodes on this route (includes links from other routes at junctions)
    links = _get_links_for_route_nodes(conn, rutenummer)
    anchor_ids = sorted(
        {
            int(node)
            for link in links
            for node in (link.get("a_node"), link.get("b_node"))
            if node is not None
        }
    )
    anchor_nodes = _fetch_anchor_nodes(conn, anchor_ids)
    anchor_names = _resolve_anchor_names_for_route(conn, anchor_nodes, anchor_ids, rutenummer)

    # Status comes only from sign_sites (matched by location), not from anchor_node_id.
    report = compute_sign_report_from_links(links, anchor_nodes, anchor_names, sign_status={})
    report["scope"] = {"rutenummer": rutenummer}
    _enrich_signs_with_sign_sites_and_route_km(conn, rutenummer, report)
    return report


def _get_links_for_prefix(conn, prefix: str) -> List[Dict[str, Any]]:
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                link_id,
                a_node,
                b_node,
                length_m,
                rutenummer_list
            FROM {ROUTE_SCHEMA}.links_with_routes
            WHERE EXISTS (
                SELECT 1
                FROM unnest(rutenummer_list) r
                WHERE r LIKE %s
            )
            ORDER BY link_id;
            """,
            (f"{prefix}%",),
        )
        rows = cur.fetchall()

    return [dict(row) for row in rows]


def _get_links_for_bbox(conn, bbox: Tuple[float, float, float, float]) -> List[Dict[str, Any]]:
    """
    Get links that intersect with a bounding box.
    
    Args:
        conn: Database connection
        bbox: Bounding box as (xmin, ymin, xmax, ymax) in WGS84 (4326)
    
    Returns:
        List of link dictionaries
    """
    if not validate_schema_name(ROUTE_SCHEMA):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")
    
    xmin, ymin, xmax, ymax = bbox
    schema_quoted = quote_identifier(ROUTE_SCHEMA)
    
    with conn.cursor(row_factory=dict_row) as cur:
        # Query links that intersect with the bbox
        # Transform bbox from WGS84 (4326) to UTM 33N (25833) for spatial query
        # Use anchor_nodes.geom column (geometry) instead of lon/lat
        cur.execute(
            f"""
            SELECT DISTINCT
                l.link_id,
                l.a_node,
                l.b_node,
                l.length_m,
                l.rutenummer_list
            FROM {schema_quoted}.links_with_routes l
            JOIN {schema_quoted}.anchor_nodes an_a ON an_a.node_id = l.a_node
            JOIN {schema_quoted}.anchor_nodes an_b ON an_b.node_id = l.b_node
            WHERE (
                ST_Intersects(
                    ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), 25833),
                    ST_Transform(an_a.geom, 25833)
                )
                OR ST_Intersects(
                    ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), 25833),
                    ST_Transform(an_b.geom, 25833)
                )
            )
            ORDER BY l.link_id;
            """,
            (xmin, ymin, xmax, ymax, xmin, ymin, xmax, ymax),
        )
        rows = cur.fetchall()
    
    return [dict(row) for row in rows]


def get_signs_for_bbox(conn, bbox: Tuple[float, float, float, float]) -> Dict[str, Any]:
    """
    Get signs report for links within a bounding box.
    
    Args:
        conn: Database connection
        bbox: Bounding box as (xmin, ymin, xmax, ymax) in WGS84 (4326)
    
    Returns:
        Signs report dictionary
    """
    links = _get_links_for_bbox(conn, bbox)
    
    if not links:
        return {
            "signs": [],
            "missing": {
                "missing_signs": [],
                "missing_destinations": [],
                "missing_anchor_names": [],
            },
            "totals": {
                "sign_count": 0,
                "endpoint_count": 0,
                "junction_count": 0,
                "destination_count": 0,
            },
            "scope": {"bbox": bbox},
        }
    
    # Collect all unique route numbers from links
    routes = sorted({
        route
        for link in links
        for route in (link.get("rutenummer_list") or [])
        if route
    })
    
    anchor_ids = sorted(
        {
            int(node)
            for link in links
            for node in (link.get("a_node"), link.get("b_node"))
            if node is not None
        }
    )
    
    anchor_nodes = _fetch_anchor_nodes(conn, anchor_ids)
    anchor_names = _resolve_anchor_names_for_prefix(conn, anchor_nodes, anchor_ids, routes)
    
    report = compute_sign_report_from_links(links, anchor_nodes, anchor_names, sign_status={})
    report["scope"] = {"bbox": bbox, "routes": routes}
    _enrich_signs_with_sign_sites_and_route_km_multi(conn, report)
    return report


def get_signs_for_prefix(conn, prefix: str) -> Dict[str, Any]:
    # Fetch routes using a separate connection to avoid transaction issues
    routes: List[str] = []
    offset = 0
    limit = 500
    with db_connection() as routes_conn:
        while True:
            page, total = get_routes_from_view(
                routes_conn,
                prefix=prefix,
                limit=limit,
                offset=offset,
                include_geometry=False,
            )
            if not page:
                break
            routes.extend([row.get("rutenummer") for row in page if row.get("rutenummer")])
            offset += len(page)
            if total is not None and offset >= total:
                break
            if len(page) < limit:
                break

    # Use the main connection for the rest of the work
    links = _get_links_for_prefix(conn, prefix)
    anchor_ids = sorted(
        {
            int(node)
            for link in links
            for node in (link.get("a_node"), link.get("b_node"))
            if node is not None
        }
    )
    anchor_nodes = _fetch_anchor_nodes(conn, anchor_ids)
    anchor_names = _resolve_anchor_names_for_prefix(conn, anchor_nodes, anchor_ids, routes)

    report = compute_sign_report_from_links(links, anchor_nodes, anchor_names, sign_status={})
    report["scope"] = {"prefix": prefix, "routes": routes}
    _enrich_signs_with_sign_sites_and_route_km_multi(conn, report)
    return report


def build_sign_production_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build production rows: one row per destination skilt (pilretning/status/farge/km per destinasjon)."""
    rows: List[Dict[str, Any]] = []
    for sign in report.get("signs", []):
        destinations = sign.get("destinations") or []
        skiltstedidentifikator = sign.get("skiltstedidentifikator") or str(sign.get("sign_site_id") or sign.get("anchor_node_id"))
        route_km = sign.get("route_km")
        back_text = sign.get("back_text") or DEFAULT_BACK_TEXT
        send_to_name = sign.get("send_to_name")
        send_to_address = sign.get("send_to_address")
        sign_name = sign.get("name")
        utm_coords = sign.get("utm_coords")
        default_site_farge = sign.get("skiltfarge")
        coords = sign.get("coordinates") or [None, None]
        front_lon = coords[0]
        front_lat = coords[1]
        back_lon = coords[0]
        back_lat = coords[1]

        if not destinations:
            pseudo_status = {
                "direction": None,
                "status": None,
                "last_inspected": None,
                "notes": None,
                "updated_by": None,
            }
            rows.append(
                _production_row(
                    sign,
                    pseudo_status,
                    None,
                    skiltstedidentifikator,
                    route_km,
                    back_text,
                    send_to_name,
                    send_to_address,
                    sign_name,
                    utm_coords,
                    default_site_farge,
                    front_lon,
                    front_lat,
                    back_lon,
                    back_lat,
                )
            )
        else:
            for destination in destinations:
                sk = destination.get("skilt") or {}
                pseudo_status = {
                    "direction": sk.get("direction"),
                    "status": sk.get("status"),
                    "last_inspected": None,
                    "notes": None,
                    "updated_by": None,
                }
                effective_farge = sk.get("skiltfarge") or default_site_farge
                dest_row = dict(destination)
                ov = sk.get("distance_meters")
                if ov is not None:
                    dest_row["distance_meters"] = ov
                rows.append(
                    _production_row(
                        sign,
                        pseudo_status,
                        dest_row,
                        skiltstedidentifikator,
                        route_km,
                        back_text,
                        send_to_name,
                        send_to_address,
                        sign_name,
                        utm_coords,
                        effective_farge,
                        front_lon,
                        front_lat,
                        back_lon,
                        back_lat,
                    )
                )
    return rows


def _production_row(
    sign: Dict,
    status: Dict,
    destination: Optional[Dict],
    skiltstedidentifikator: str,
    route_km: Optional[float],
    back_text: str,
    send_to_name: Optional[str],
    send_to_address: Optional[str],
    sign_name: Optional[str],
    utm_coords: Optional[str],
    skiltfarge: Optional[str],
    front_lon: Optional[float],
    front_lat: Optional[float],
    back_lon: Optional[float],
    back_lat: Optional[float],
) -> Dict[str, Any]:
    """Single production row with Norwegian and baksidetekst columns."""
    dest_name = destination.get("name") if destination else None
    dest_anchor_id = destination.get("anchor_node_id") if destination else None
    distance_meters = destination.get("distance_meters") if destination else None
    return {
        "anchor_node_id": sign.get("anchor_node_id"),
        "sign_site_id": sign.get("sign_site_id"),
        "skiltstedidentifikator": skiltstedidentifikator,
        "tekst_paa_skiltet_destinasjon": dest_name,
        "km": route_km,
        "pilretning": status.get("direction"),
        "sendes_til_navn": send_to_name,
        "sendes_til_adresse": send_to_address,
        "skiltstednavn": sign_name,
        "utm_koordinater": utm_coords,
        "baksidetekst": back_text,
        "skiltfarge": skiltfarge,
        "sign_name": sign_name,
        "direction": status.get("direction"),
        "status": status.get("status"),
        "destination_name": dest_name,
        "destination_anchor_id": dest_anchor_id,
        "distance_meters": distance_meters,
        "front_lon": front_lon,
        "front_lat": front_lat,
        "back_lon": back_lon,
        "back_lat": back_lat,
        "last_inspected": status.get("last_inspected"),
        "notes": status.get("notes"),
        "updated_by": status.get("updated_by"),
    }
