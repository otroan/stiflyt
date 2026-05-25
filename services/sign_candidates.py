"""Sign candidate computation for the focused Breheimen signs tool.

Reshapes the existing sign-report output (see services.signs) into the schema
the new signs_app frontend consumes. Applies the user-specified rules:

  - One panel per *destination name* (not per anchor_node_id). If multiple routes
    reach the same named destination, the routes are listed but only one panel
    is emitted, using the shortest distance.
  - Distance correction: raw along-route metres are multiplied by
    DISTANCE_CORRECTION_FACTOR (1.125 — DB lines under-measure physical reality).
  - Distance rounding: <10 km rounds DOWN to nearest 0.5 km; >=10 km rounds to
    nearest whole km.
  - Sign back: anchor name + UTM 32V coordinates. The utm library auto-selects
    zone 32V for points in Breheimen (lon ~7°E, lat ~61°N).
  - Default panel colour: trehvit.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .signs import (
    _fetch_anchor_nodes,
    _resolve_anchor_names_for_prefix,
    compute_sign_report_from_links,
)
from .route_service import (
    wgs84_to_utm_display,
    get_route_endpoint_nodes_and_length,
)
from .operational_database import op_db_connection
from .operational_store import (
    get_sign_sites_status_by_area_anchor,
    get_sign_site_skilt_full,
    get_endpoint_names_for_anchors,
    get_distance_correction_factor,
    DEFAULT_DISTANCE_CORRECTION,
)
from .database import validate_schema_name, quote_identifier
from ._timing import phase_timer
import os


DEFAULT_PANEL_COLOR = "trehvit"

# Fully-qualified name of the patched fotruteinfo view. This applies the
# ops.rutenummer_remap errata transparently — see migration 015 and
# `data/route_errata.yaml`. Every SQL in this module reads from here instead
# of `stiflyt.fotruteinfo` so the remap propagates to filter, dedup,
# endpoint detection, route summary, manual-sign snap — everything.
FOTRUTEINFO_VIEW = "ops.fotruteinfo_patched"


def correct_distance_km(distance_meters: Optional[float], factor: float = DEFAULT_DISTANCE_CORRECTION) -> Optional[float]:
    """Apply per-area correction factor then round per spec.

    <10 km: floor to nearest 0.5 km (so 7.65 -> 7.5).
    >=10 km: round to nearest whole km (so 13.84 -> 14).

    `factor` defaults to 1.125 (the historical hiking-community heuristic);
    callers within an area lookup it from `ops.distance_correction` for that
    area first.
    """
    if distance_meters is None:
        return None
    km = (float(distance_meters) / 1000.0) * factor
    if km < 10.0:
        return math.floor(km * 2.0) / 2.0
    return float(round(km))


def format_utm32v_block(lon: Optional[float], lat: Optional[float]) -> Optional[str]:
    """Multi-line UTM coordinate block, rounded to the nearest 10 m.

    Layout (Norwegian convention):

        UTM 32V
        E 432150
        N 6854120

    Zone is computed from the point — Breheimen lands in 32V. 10 m precision
    matches what a handheld GPS can realistically deliver (and the sign-post
    placement accuracy in practice).
    """
    if lon is None or lat is None:
        return None
    try:
        import utm  # local import keeps top of module clean
        easting, northing, zone_number, zone_letter = utm.from_latlon(lat, lon)
    except (ValueError, Exception):
        return None
    e10 = int(round(easting / 10.0)) * 10
    n10 = int(round(northing / 10.0)) * 10
    return f"UTM {zone_number}{zone_letter}\nE {e10}\nN {n10}"


def format_sign_back(anchor_name: Optional[str], lon: Optional[float], lat: Optional[float]) -> str:
    """Sign back text: anchor name followed by a UTM 32V coordinate block."""
    parts: List[str] = []
    if anchor_name:
        parts.append(anchor_name)
    block = format_utm32v_block(lon, lat)
    if block:
        parts.append(block)
    return "\n".join(parts)


def _route_adjacency_with_links(route_links_list: List[Dict[str, Any]]) -> Dict[int, List[tuple]]:
    """Build adjacency (node -> [(neighbor, length_m, link_id), ...]) for one route."""
    adj: Dict[int, List[tuple]] = {}
    for link in route_links_list:
        a = link.get("a_node")
        b = link.get("b_node")
        length = link.get("length_m") or link.get("length_meters") or 0.0
        link_id = link.get("link_id")
        if a is None or b is None or link_id is None:
            continue
        try:
            a_i, b_i = int(a), int(b)
            length_f = float(length)
            link_id_i = int(link_id)
        except (TypeError, ValueError):
            continue
        adj.setdefault(a_i, []).append((b_i, length_f, link_id_i))
        adj.setdefault(b_i, []).append((a_i, length_f, link_id_i))
    return adj


def _build_route_chain(
    route_links: List[Dict[str, Any]],
    start_node: int,
) -> Dict[int, Dict[str, Any]]:
    """1-D walk of a route's link subgraph from a starting endpoint.

    Returns Dict[node_id, {pos_m, prev_link_id}] — the cumulative distance
    from `start_node` to each reachable node along the chain, and the link
    that was last traversed to reach it. The route's link subgraph is
    expected to be a tree (typically a simple chain, A — link — n1 — link
    — … — B). For a clean chain, this is exactly equivalent to Dijkstra
    but simpler.

    If a route's subgraph branches (degree > 2 at some node), BFS still
    converges but picks the first path encountered — which is "shortest"
    in the chain sense for our data (no real branches observed in bre).
    """
    adj = _route_adjacency_with_links(route_links)
    out: Dict[int, Dict[str, Any]] = {start_node: {"pos_m": 0.0, "prev_link_id": None}}
    queue: List[int] = [start_node]
    while queue:
        cur = queue.pop(0)
        cur_pos = out[cur]["pos_m"]
        for neighbor, length, link_id in adj.get(cur, []):
            if neighbor in out:
                continue
            out[neighbor] = {"pos_m": cur_pos + length, "prev_link_id": link_id}
            queue.append(neighbor)
    return out


def _snap_to_route_chain(
    conn,
    lon: float,
    lat: float,
    rutenummer: str,
    chain: Dict[int, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Project a click onto a route and return its 1-D position along the chain.

    Finds the link in the route's subgraph that's closest to (lon, lat),
    computes the fraction along that link via ST_LineMerge → ST_LineLocatePoint,
    and figures out which of the link's nodes is "earlier" in the chain
    (smaller pos_m). Then snap_pos_m = earlier_node.pos_m + (fraction toward
    later end) × link.length_m.

    Returns {pos_m, on_link_id, on_link_a_node, on_link_b_node, dist_to_click_m}
    or None.
    """
    if not chain:
        return None
    schema = os.getenv("ROUTE_SCHEMA", "stiflyt")
    if not validate_schema_name(schema):
        return None
    schema_quoted = quote_identifier(schema)
    from psycopg.rows import dict_row
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            WITH route_links AS (
                SELECT l.link_id, l.a_node, l.b_node,
                       ST_LineMerge(l.geom) AS line_geom,
                       l.length_m,
                       n_a.geom AS a_geom
                FROM {FOTRUTEINFO_VIEW} fi
                JOIN {schema_quoted}.link_segments ls ON ls.segment_id = fi.fotrute_fk
                JOIN {schema_quoted}.links l ON l.link_id = ls.link_id
                JOIN {schema_quoted}.nodes n_a ON n_a.node_id = l.a_node
                WHERE fi.rutenummer = %s
                GROUP BY l.link_id, l.a_node, l.b_node, l.geom, l.length_m, n_a.geom
            ),
            click AS (
                SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833) AS p
            )
            SELECT rl.link_id, rl.a_node, rl.b_node, rl.length_m,
                   ST_LineLocatePoint(rl.line_geom, c.p) AS f_merge,
                   ST_Distance(ST_StartPoint(rl.line_geom), rl.a_geom) AS dist_start_to_a,
                   ST_Distance(rl.line_geom, c.p) AS dist_to_click_m
            FROM route_links rl, click c
            WHERE GeometryType(rl.line_geom) = 'LINESTRING'
            ORDER BY ST_Distance(rl.line_geom, c.p) ASC
            LIMIT 1;
            """,
            (rutenummer, lon, lat),
        )
        row = cur.fetchone()
    if not row or row.get("link_id") is None:
        return None
    a_node = int(row["a_node"])
    b_node = int(row["b_node"])
    length_m = float(row["length_m"] or 0.0)
    f_merge = float(row["f_merge"] or 0.0)
    starts_at_a = float(row["dist_start_to_a"] or 0.0) < 0.5  # 0.5 m tolerance
    f_from_a = f_merge if starts_at_a else (1.0 - f_merge)
    pos_a = chain.get(a_node, {}).get("pos_m")
    pos_b = chain.get(b_node, {}).get("pos_m")
    if pos_a is None or pos_b is None:
        return None
    # Earlier node = the one closer to start_node in the chain.
    if pos_a <= pos_b:
        snap_pos_m = pos_a + f_from_a * length_m
    else:
        snap_pos_m = pos_b + (1.0 - f_from_a) * length_m
    return {
        "pos_m": snap_pos_m,
        "on_link_id": int(row["link_id"]),
        "on_link_a_node": a_node,
        "on_link_b_node": b_node,
        "dist_to_click_m": float(row["dist_to_click_m"] or 0.0),
    }


def _first_link_toward_endpoint(
    anchor_node: int,
    endpoint_node: int,
    chain: Dict[int, Dict[str, Any]],
    route_links: List[Dict[str, Any]],
) -> Optional[int]:
    """The link_id of the first link out of `anchor_node` along the chain
    toward `endpoint_node`. Direction is decided by chain position: the
    endpoint is either at a smaller pos (going "back") or larger pos
    (going "forward"). For a chain (no branches), exactly one of the
    anchor's neighbours will be in that direction.
    """
    anchor_pos = chain.get(anchor_node, {}).get("pos_m")
    endpoint_pos = chain.get(endpoint_node, {}).get("pos_m")
    if anchor_pos is None or endpoint_pos is None:
        return None
    target_is_earlier = endpoint_pos < anchor_pos
    adj = _route_adjacency_with_links(route_links)
    for neighbor, _length, link_id in adj.get(anchor_node, []):
        n_pos = chain.get(neighbor, {}).get("pos_m")
        if n_pos is None:
            continue
        if target_is_earlier and n_pos < anchor_pos:
            return link_id
        if (not target_is_earlier) and n_pos > anchor_pos:
            return link_id
    return None


def _build_route_topology(
    links: List[Dict[str, Any]],
) -> tuple:
    """Returns (route_links_by_route, route_endpoints_by_route, all_routes)."""
    route_links: Dict[str, List[Dict[str, Any]]] = {}
    for link in links:
        for r in link.get("rutenummer_list") or []:
            route_links.setdefault(r, []).append(link)
    route_endpoints: Dict[str, set] = {}
    for r, ll in route_links.items():
        node_counts: Dict[int, int] = {}
        for link in ll:
            for n in (link.get("a_node"), link.get("b_node")):
                if n is None:
                    continue
                try:
                    ni = int(n)
                except (TypeError, ValueError):
                    continue
                node_counts[ni] = node_counts.get(ni, 0) + 1
        route_endpoints[r] = {n for n, c in node_counts.items() if c == 1}
    return route_links, route_endpoints


def _compute_panels_for_sign(
    sign_node: int,
    sign_routes: set,
    route_links_by_route: Dict[str, List[Dict[str, Any]]],
    route_endpoints_by_route: Dict[str, set],
    anchor_names: Dict[int, Dict[str, Any]],
    chain_by_route: Optional[Dict[str, Dict[int, Dict[str, Any]]]] = None,
    all_route_endpoints: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Panels for one anchor sign.

    A sign emits a panel for every "place worth pointing at" reached by
    walking each of its routes in either direction. "Worth pointing at"
    is the strict rule: a node `X` is a destination from this sign iff
    `X` is itself a degree-1 endpoint of SOME route in the area
    (typically because another route terminates there). This catches:

      - The route's own terminus (it's an endpoint of *this* route).
      - Interior junctions where other routes end. E.g. bre26 from
        Sunndalen toward Framrusti passes through Skridulaupbu — which
        isn't bre26's endpoint, but IS where some other route terminates.
        That's worth a panel.

    Dedup is still by (destination_name, first_link_out_of_sign): routes
    leaving on the same physical link to the same name merge; parallel-
    path siblings stay separate.

    `chain_by_route` and `all_route_endpoints` are precomputed at the
    request level (see get_sign_candidates_for_area) to avoid rebuilding
    per-sign.
    """
    if all_route_endpoints is None:
        all_route_endpoints = set()
        for r_eps in route_endpoints_by_route.values():
            all_route_endpoints.update(r_eps)

    grouped: Dict[tuple, Dict[str, Any]] = {}
    for route in sign_routes:
        rls = route_links_by_route.get(route)
        eps = route_endpoints_by_route.get(route)
        if not rls or not eps:
            continue
        chain = chain_by_route.get(route) if chain_by_route is not None else None
        if chain is None:
            anchor_start = min(eps)
            chain = _build_route_chain(rls, anchor_start)
        anchor_pos = chain.get(sign_node, {}).get("pos_m")
        if anchor_pos is None:
            continue  # sign not on this route's connected component
        for node, info in chain.items():
            if node == sign_node:
                continue
            # Strict rule: only nodes that are endpoints of *some* route
            # (i.e. somewhere a route terminates) become destinations.
            if node not in all_route_endpoints:
                continue
            node_pos = info.get("pos_m")
            if node_pos is None:
                continue
            distance_m = abs(node_pos - anchor_pos)
            first_link = _first_link_toward_endpoint(sign_node, node, chain, rls)
            name_info = anchor_names.get(node) or {}
            name = (name_info.get("name") or "").strip() or f"Anchor {node}"
            key = (name, first_link)
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = {
                    "destination_name": name,
                    "destination_anchor_node_id": node,
                    "first_link_id": first_link,
                    "route_numbers": [route],
                    "distance_m_db": distance_m,
                }
            else:
                if distance_m < existing["distance_m_db"]:
                    existing["distance_m_db"] = distance_m
                    existing["destination_anchor_node_id"] = node
                if route not in existing["route_numbers"]:
                    existing["route_numbers"].append(route)
    panels = sorted(grouped.values(), key=lambda p: (p["distance_m_db"] or 0.0, p["destination_name"]))
    _auto_disambiguate_panels(panels)
    return panels


_SAME_PLACE_RADIUS_M = 100.0


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres. Sufficient at 100 m scale where
    even a flat-earth approximation would be fine — Haversine is just as cheap."""
    import math
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def _cluster_sites_by_name_and_proximity(
    sites: List[Dict[str, Any]],
    radius_m: float = _SAME_PLACE_RADIUS_M,
) -> List[List[int]]:
    """Group indices of `sites` whose anchors share a (validated) name AND are
    within `radius_m` of each other. Manual signs, unnamed candidates, and
    sites lacking coordinates are each their own one-element cluster.

    The convention 'same place if name matches AND proximity is small' was
    picked because:
      - name alone could merge real-life duplicates ('Løypa') in different valleys;
      - proximity alone could merge unrelated anchors at the same junction.
    Requiring both is the conservative choice; you'll only get merges where
    a human has explicitly validated the name on both anchors.
    """
    groups: List[List[int]] = []
    used = [False] * len(sites)

    def _is_validated(site: Dict[str, Any]) -> bool:
        # The auto fallback name 'Anchor 80712' isn't a human-validated name —
        # don't merge those. Manual signs also opt out (they don't have an
        # anchor and shouldn't cluster with anchor-based signs).
        if site.get("is_manual"):
            return False
        n = (site.get("name") or "").strip()
        if not n:
            return False
        if n.lower().startswith("anchor "):
            return False
        return True

    for i, s in enumerate(sites):
        if used[i]:
            continue
        if not _is_validated(s) or s.get("lon") is None or s.get("lat") is None:
            groups.append([i])
            used[i] = True
            continue
        name_i = s["name"].strip().lower()
        cluster = [i]
        used[i] = True
        for j in range(i + 1, len(sites)):
            if used[j]:
                continue
            t = sites[j]
            if not _is_validated(t) or t.get("lon") is None or t.get("lat") is None:
                continue
            if t["name"].strip().lower() != name_i:
                continue
            if _haversine_m(s["lon"], s["lat"], t["lon"], t["lat"]) <= radius_m:
                cluster.append(j)
                used[j] = True
        groups.append(cluster)
    return groups


def _merge_clustered_sites(sites: List[Dict[str, Any]], cluster_idxs: List[int]) -> Dict[str, Any]:
    """Combine several sign-sites that represent the same physical place into
    one merged site. The site with the smallest anchor_node_id is the
    'primary' — its coordinates, sign_site_id, status, and overrides carry
    through. Panels from secondaries are absorbed and deduped by
    destination_anchor_node_id; self-reference panels (a sign panel pointing
    to another anchor in the same cluster) are dropped.

    Note: first_link_id is no longer meaningful across a merge (it was
    measured relative to a specific anchor's outgoing topology) so we clear
    it. Parallel-path siblings sharing a merged origin get collapsed.
    """
    sorted_idxs = sorted(
        cluster_idxs,
        key=lambda i: sites[i].get("anchor_node_id") if sites[i].get("anchor_node_id") is not None else 1 << 62,
    )
    primary = dict(sites[sorted_idxs[0]])
    cluster_anchor_ids = {
        sites[i].get("anchor_node_id")
        for i in cluster_idxs
        if sites[i].get("anchor_node_id") is not None
    }

    by_dest: Dict[Any, Dict[str, Any]] = {}
    for i in sorted_idxs:
        for p in sites[i].get("panels") or []:
            # Drop panels pointing at another anchor in the same cluster —
            # otherwise the merged Nørdstedalseter shows "Nørdstedalseter 0 km".
            if p.get("destination_anchor_node_id") in cluster_anchor_ids:
                continue
            key = (
                p.get("destination_anchor_node_id")
                if p.get("destination_anchor_node_id") is not None
                else f"name:{p['destination_name']}"
            )
            if key in by_dest:
                existing = by_dest[key]
                new_d = p.get("distance_m_db")
                old_d = existing.get("distance_m_db")
                if new_d is not None and (old_d is None or new_d < old_d):
                    existing["distance_m_db"] = new_d
                    existing["distance_km_displayed"] = p.get("distance_km_displayed")
                    existing["destination_name"] = p.get("destination_name")
                for r in p.get("route_numbers") or []:
                    if r not in existing["route_numbers"]:
                        existing["route_numbers"].append(r)
            else:
                merged_panel = dict(p)
                # first_link_id is anchor-relative; meaningless after merge.
                merged_panel["first_link_id"] = None
                merged_panel["route_numbers"] = list(merged_panel.get("route_numbers") or [])
                by_dest[key] = merged_panel

    merged_panels = sorted(
        by_dest.values(),
        key=lambda p: (p.get("distance_m_db") or 0.0, p.get("destination_name") or ""),
    )

    # Union all route numbers across the cluster for the site-level display.
    all_routes: set = set()
    for i in cluster_idxs:
        all_routes.update(sites[i].get("route_numbers") or [])

    primary["route_numbers"] = sorted(all_routes)
    primary["panels"] = merged_panels
    primary["merged_from_anchors"] = sorted(int(a) for a in cluster_anchor_ids)
    return primary


def _auto_disambiguate_panels(panels: List[Dict[str, Any]]) -> None:
    """When two+ panels at the same sign share destination_name but differ on
    first_link_id (parallel-path case), suffix each with its rutenummer set
    so they don't read identically on the sign. User can override via
    sign_site_skilt.destination_name to get nicer labels like
    'Arentzbu - Sætersti' vs 'Arentzbu - Skogssti'."""
    from collections import Counter
    counts = Counter(p["destination_name"] for p in panels)
    for p in panels:
        if counts[p["destination_name"]] > 1:
            routes_str = ", ".join(p["route_numbers"])
            p["destination_name"] = f"{p['destination_name']} ({routes_str})"


def _apply_panel_overrides(
    panels: List[Dict[str, Any]],
    overrides_for_site: List[Dict[str, Any]],
    correction_factor: float = DEFAULT_DISTANCE_CORRECTION,
) -> List[Dict[str, Any]]:
    """Apply per-panel overrides from sign_site_skilt to a panel list.

    Each override row carries (anchor_node_id, first_link_id). A panel matches
    when both equal — so parallel-path panels sharing an anchor stay independent.
    If no exact match is found, we fall back to the row with first_link_id IS NULL
    (the legacy "no-discriminator" slot from before the split-panel logic).
    """
    # Index overrides by (anchor_node_id, first_link_id)
    by_key: Dict[tuple, Dict[str, Any]] = {}
    for ov in overrides_for_site or []:
        aid = ov.get("anchor_node_id")
        fl = ov.get("first_link_id")
        if aid is None:
            continue
        by_key[(int(aid), int(fl) if fl is not None else None)] = ov

    out: List[Dict[str, Any]] = []
    for p in panels:
        aid = p.get("destination_anchor_node_id")
        fl = p.get("first_link_id")
        ov = None
        if aid is not None:
            ov = by_key.get((int(aid), int(fl) if fl is not None else None))
            if ov is None and fl is not None:
                # Legacy fallback: a row written before split-by-link existed.
                ov = by_key.get((int(aid), None))
        merged = dict(p)
        if ov:
            if ov.get("skiltfarge"):
                merged["color"] = ov["skiltfarge"]
            if ov.get("direction") is not None:
                merged["direction"] = ov["direction"]
            if ov.get("destination_name"):
                merged["destination_name"] = ov["destination_name"]
            if ov.get("distance_meters") is not None:
                merged["distance_m_db"] = ov["distance_meters"]
                merged["distance_km_displayed"] = correct_distance_km(ov["distance_meters"], correction_factor)
        out.append(merged)
    return out


def _panels_from_sign(sign: Dict[str, Any], correction_factor: float) -> List[Dict[str, Any]]:
    """Translate the sign's already-grouped destinations (from
    _compute_panels_for_sign) into the API panel shape: distance correction,
    default color, null direction. Grouping by (destination, first_link) is
    done upstream."""
    out: List[Dict[str, Any]] = []
    for p in sign.get("destinations") or []:
        out.append(
            {
                "destination_name": p["destination_name"],
                "destination_anchor_node_id": p.get("destination_anchor_node_id"),
                "route_numbers": list(p.get("route_numbers") or []),
                "first_link_id": p.get("first_link_id"),
                "distance_m_db": p.get("distance_m_db"),
                "distance_km_displayed": correct_distance_km(p.get("distance_m_db"), correction_factor),
                "color": DEFAULT_PANEL_COLOR,
                "direction": None,
            }
        )
    return out


def _route_endpoints_bulk(conn, rutenummers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fast bulk: per-route first_a_node + last_b_node + length_m for many routes.

    Replaces N calls to `get_route_endpoint_nodes_and_length` (which goes through
    the slow links_with_routes view + per-route GeoJSON length, ~0.9 s each).
    Pulls length from `stiflyt.routes.total_length_m` (already aggregated) and
    derives endpoint nodes from link_segments + fotruteinfo in a single query.

    Returns: rutenummer -> {first_a_node, last_b_node, length_m}.
    """
    if not rutenummers:
        return {}
    schema = os.getenv("ROUTE_SCHEMA", "stiflyt")
    if not validate_schema_name(schema):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {schema}")
    schema_quoted = quote_identifier(schema)
    from psycopg.rows import dict_row
    # Endpoints are the degree-1 nodes in each route's subgraph (the actual
    # topology endpoints). The old logic — `first_a_node` of the lowest
    # link_id and `last_b_node` of the highest — was picking arbitrary middle
    # nodes because link_id ordering doesn't correspond to route traversal.
    # When a route has more than 2 degree-1 nodes (disconnected components),
    # we pick the geographically farthest-apart pair, which gives the route's
    # logical extremes.
    sql = f"""
        WITH route_links AS (
            SELECT fi.rutenummer, l.link_id, l.a_node, l.b_node
            FROM {FOTRUTEINFO_VIEW} fi
            JOIN {schema_quoted}.link_segments ls ON ls.segment_id = fi.fotrute_fk
            JOIN {schema_quoted}.links l ON l.link_id = ls.link_id
            WHERE fi.rutenummer = ANY(%s)
            GROUP BY fi.rutenummer, l.link_id, l.a_node, l.b_node
        ),
        degrees AS (
            SELECT rutenummer, node_id, COUNT(*) AS deg
            FROM (
                SELECT rutenummer, a_node AS node_id FROM route_links
                UNION ALL
                SELECT rutenummer, b_node AS node_id FROM route_links
            ) x
            GROUP BY rutenummer, node_id
        ),
        degree_one AS (
            SELECT d.rutenummer, d.node_id, an.geom
            FROM degrees d
            LEFT JOIN {schema_quoted}.anchor_nodes an ON an.node_id = d.node_id
            WHERE d.deg = 1
        ),
        pairs AS (
            -- For routes with exactly 2 degree-1 nodes (the common case for
            -- connected routes), this returns the single (e1, e2) pair.
            -- For routes with many degree-1 nodes (disconnected), we pick
            -- the farthest-apart pair as the canonical endpoints.
            SELECT DISTINCT ON (e1.rutenummer)
                e1.rutenummer,
                e1.node_id AS first_a_node,
                e2.node_id AS last_b_node,
                ST_Distance(e1.geom, e2.geom) AS endpoint_distance_m
            FROM degree_one e1
            JOIN degree_one e2
              ON e2.rutenummer = e1.rutenummer
             AND e2.node_id > e1.node_id
            ORDER BY e1.rutenummer, ST_Distance(e1.geom, e2.geom) DESC NULLS LAST
        ),
        lengths AS (
            -- Sum link lengths via the patched fotruteinfo view so the total
            -- reflects ops.rutenummer_remap edits (stiflyt.routes.total_length_m
            -- is a pre-patch materialized aggregate and would understate any
            -- route that has absorbed patched segments).
            SELECT rl.rutenummer, SUM(rl.length_m) AS length_m
            FROM (
                SELECT DISTINCT fi.rutenummer, l.link_id, l.length_m
                FROM {FOTRUTEINFO_VIEW} fi
                JOIN {schema_quoted}.link_segments ls ON ls.segment_id = fi.fotrute_fk
                JOIN {schema_quoted}.links l ON l.link_id = ls.link_id
                WHERE fi.rutenummer = ANY(%s)
            ) rl
            GROUP BY rl.rutenummer
        )
        SELECT
            p.rutenummer,
            p.first_a_node,
            p.last_b_node,
            l.length_m
        FROM pairs p
        LEFT JOIN lengths l USING (rutenummer);
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (rutenummers, rutenummers))
        out: Dict[str, Dict[str, Any]] = {}
        for r in cur.fetchall():
            out[r["rutenummer"]] = {
                "first_a_node": int(r["first_a_node"]) if r.get("first_a_node") is not None else None,
                "last_b_node": int(r["last_b_node"]) if r.get("last_b_node") is not None else None,
                "length_m": float(r["length_m"]) if r.get("length_m") is not None else 0.0,
            }
        return out


def _manual_site_panels(
    rutenummer_list: List[str],
    snap_pos_by_route: Dict[str, float],
    endpoints_by_route: Dict[str, Dict[str, Any]],
    chain_by_route: Dict[str, Dict[int, Dict[str, Any]]],
    names_by_anchor: Dict[int, Dict[str, Any]],
    correction_factor: float = DEFAULT_DISTANCE_CORRECTION,
) -> List[Dict[str, Any]]:
    """Panels for a manual sign that may belong to several routes.

    For each route the sign is on, we have a 1-D `snap_pos_m` along the
    route's chain and the route's two endpoints. Distance from the sign to
    each endpoint is just the difference in chain positions.
    """
    if not rutenummer_list:
        return []

    candidates: List[Dict[str, Any]] = []
    for rutenummer in rutenummer_list:
        ep = endpoints_by_route.get(rutenummer)
        if not ep:
            continue
        snap_pos = snap_pos_by_route.get(rutenummer)
        chain = chain_by_route.get(rutenummer) or {}
        if snap_pos is None or not chain:
            continue
        for aid in (ep.get("first_a_node"), ep.get("last_b_node")):
            if aid is None:
                continue
            ep_pos = chain.get(aid, {}).get("pos_m")
            if ep_pos is None:
                # Endpoint on a different connected component from the snap.
                # Skip — user can manually override if they want to fake a value.
                continue
            distance_m = abs(ep_pos - snap_pos)
            n = (names_by_anchor.get(aid) or {}).get("name") or f"Anchor {aid}"
            candidates.append({
                "destination_name": n,
                "destination_anchor_node_id": aid,
                "rutenummer": rutenummer,
                "distance_m_db": float(distance_m),
                # No "first link out of a junction" concept for a manual sign.
                "first_link_id": None,
            })

    # Group by destination_anchor_node_id — multiple routes reaching the same
    # anchor (typical for shared-segment manual signs: bre4 + bre52 both end
    # at Nørdstedalseter = node 89398) collapse into one panel that lists all
    # contributing routes. Anchor id is the unambiguous identity; the name
    # follows it. Candidates without an anchor id (free-text destinations,
    # currently never produced) fall back to grouping by name.
    grouped: Dict[Any, Dict[str, Any]] = {}
    for c in candidates:
        key = c["destination_anchor_node_id"] if c["destination_anchor_node_id"] is not None else c["destination_name"]
        if key in grouped:
            existing = grouped[key]
            # Keep the shortest distance — for a shared-segment sign all the
            # candidates should be within ~10 m of each other anyway.
            if c["distance_m_db"] < existing["distance_m_db"]:
                existing["distance_m_db"] = c["distance_m_db"]
            if c["rutenummer"] not in existing["route_numbers"]:
                existing["route_numbers"].append(c["rutenummer"])
        else:
            grouped[key] = {
                "destination_name": c["destination_name"],
                "destination_anchor_node_id": c["destination_anchor_node_id"],
                "route_numbers": [c["rutenummer"]],
                "distance_m_db": c["distance_m_db"],
                "first_link_id": c["first_link_id"],
            }

    panels: List[Dict[str, Any]] = sorted(
        grouped.values(),
        key=lambda p: (p["distance_m_db"] or 0.0, p["destination_name"]),
    )
    out: List[Dict[str, Any]] = []
    for p in panels:
        out.append({
            "destination_name": p["destination_name"],
            "destination_anchor_node_id": p["destination_anchor_node_id"],
            "route_numbers": p["route_numbers"],
            "distance_m_db": p["distance_m_db"],
            "distance_km_displayed": correct_distance_km(p["distance_m_db"], correction_factor),
            "color": DEFAULT_PANEL_COLOR,
            "direction": None,
            "first_link_id": p.get("first_link_id"),
        })
    return out


# (Dijkstra-based snap-to-endpoint computation removed; replaced by
# _build_route_chain + _snap_to_route_chain which give the same result on
# the chain-shaped routes we actually have, with fewer moving parts.)


def _fetch_manual_sites_for_area(op_conn, area_code: str) -> List[Dict[str, Any]]:
    """Manual sign sites in an area (anchor_node_id IS NULL)."""
    schema = os.getenv("OP_SCHEMA", "ops")
    if not validate_schema_name(schema):
        return []
    schema_quoted = quote_identifier(schema)
    from psycopg.rows import dict_row
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, site_code, status, name, rutenummer, rutenummer_list, route_km,
                   ST_X(ST_Transform(geom, 4326)) AS lon,
                   ST_Y(ST_Transform(geom, 4326)) AS lat
            FROM {schema_quoted}.sign_sites
            WHERE area_code = %s AND anchor_node_id IS NULL
              AND status <> 'rejected'
            ORDER BY id;
            """,
            (area_code,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_route_summary_for_area(conn, area_code: str, *, timings: Optional[list] = None) -> Dict[str, Any]:
    """Per-route summary for the signs_app route hover popup AND the map's
    line layer.

    Returns rutenummer -> start_name, end_name, length_m, length_km_displayed,
    route_geometry (GeoJSON MultiLineString, WGS84). Everything is fetched
    through `ops.fotruteinfo_patched` so any rutenummer remap (see migration
    015 / data/route_errata.yaml) is reflected end-to-end — including the
    rendered line on the map.

    Names come from `ops.endpoint_names` (the validated layer); if no validated
    name exists for an endpoint anchor, the field is null and the UI falls
    back to the rutenummer alone.

    Phase timings are appended to `timings` if provided (Server-Timing).
    """
    _t = timings if timings is not None else []
    with phase_timer(_t, "links_query"):
        links = _fetch_links_for_prefix_fast(conn, area_code)
    rutenummers = sorted({r for L in links for r in (L.get("rutenummer_list") or [])})
    if not rutenummers:
        return {"area_code": area_code, "routes": []}
    with phase_timer(_t, "route_endpoints"):
        endpoints = _route_endpoints_bulk(conn, rutenummers)
    # Pull total_length_m + rutenavn from stiflyt.routes (sum of all segments).
    with phase_timer(_t, "route_meta"):
        route_meta = _route_total_lengths_and_names(conn, rutenummers)
    anchor_ids = sorted({
        aid
        for ep in endpoints.values()
        for aid in (ep.get("first_a_node"), ep.get("last_b_node"))
        if aid is not None
    })
    with phase_timer(_t, "endpoint_names"):
        with op_db_connection() as op_conn:
            correction_factor = get_distance_correction_factor(op_conn, area_code)
            names = get_endpoint_names_for_anchors(op_conn, anchor_ids) if anchor_ids else {}

    # Per-route MultiLineString geometry, assembled from fotrute.senterlinje
    # via the *patched* fotruteinfo view, transformed to WGS84 GeoJSON for the
    # map line layer. This is the only place the signs_app pulls route shapes
    # so the errata patch reflects in the rendered line — bre26 absorbs the
    # 20160407 segments visually.
    with phase_timer(_t, "route_geometries"):
        geometries = _route_geometries_for_rutenummers(conn, rutenummers)

    out: List[Dict[str, Any]] = []
    for rn in rutenummers:
        ep = endpoints.get(rn) or {}
        first = ep.get("first_a_node")
        last = ep.get("last_b_node")
        meta = route_meta.get(rn) or {}
        total_m = meta.get("total_length_m") or 0.0
        rutenavn = meta.get("rutenavn")
        # 1) validated name from ops.endpoint_names
        start_name = (names.get(first) or {}).get("name") if first is not None else None
        end_name = (names.get(last) or {}).get("name") if last is not None else None
        # 2) fall back to parsed rutenavn ('Skjolden - Arentzbu'); we don't
        #    know which half maps to which endpoint, so the popup also gets
        #    the raw rutenavn so it can show it bidirectionally.
        if not start_name or not end_name:
            a, b = _parse_rutenavn_endpoints(rutenavn)
            if a and b:
                start_name = start_name or a
                end_name = end_name or b
        out.append({
            "rutenummer": rn,
            "rutenavn": rutenavn,
            "start_anchor_node_id": first,
            "end_anchor_node_id": last,
            "start_name": start_name,
            "end_name": end_name,
            "length_m": total_m,
            "length_km_displayed": correct_distance_km(total_m, correction_factor),
            "route_geometry": geometries.get(rn),
        })
    return {"area_code": area_code, "routes": out}


def get_area_stats(conn, area_code: str) -> Dict[str, Any]:
    """Headline numbers for the "Om området" report.

    Only returns what the frontend can't easily derive from the candidates +
    route-summary payloads it already has — namely the unique trail length
    (sum of physical link lengths, with each shared segment counted once).
    Everything else (sign counts, panels) is aggregated client-side from the
    already-loaded /candidates response, so this endpoint stays cheap and
    avoids re-doing the candidate compute.
    """
    links = _fetch_links_for_prefix_fast(conn, area_code)
    rutenummers = sorted({r for L in links for r in (L.get("rutenummer_list") or [])})
    unique_length_m = sum(float(L.get("length_m") or 0.0) for L in links)
    with op_db_connection() as op_conn:
        correction_factor = get_distance_correction_factor(op_conn, area_code)
    return {
        "area_code": area_code,
        "total_routes": len(rutenummers),
        "unique_trail_length_m": unique_length_m,
        "unique_trail_length_km_displayed": correct_distance_km(unique_length_m, correction_factor),
        "distance_correction_factor": correction_factor,
    }


def _route_geometries_for_rutenummers(conn, rutenummers: List[str]) -> Dict[str, Any]:
    """Per-route GeoJSON MultiLineString (WGS84) assembled from
    `ops.fotruteinfo_patched` so the rendered line reflects errata patches."""
    if not rutenummers:
        return {}
    schema = os.getenv("ROUTE_SCHEMA", "stiflyt")
    if not validate_schema_name(schema):
        return {}
    schema_quoted = quote_identifier(schema)
    from psycopg.rows import dict_row
    sql = f"""
        SELECT
            fi.rutenummer,
            ST_AsGeoJSON(
                ST_Multi(ST_Transform(ST_Collect(f.senterlinje), 4326))
            )::json AS route_geometry
        FROM {FOTRUTEINFO_VIEW} fi
        JOIN {schema_quoted}.fotrute f ON f.objid = fi.fotrute_fk
        WHERE fi.rutenummer = ANY(%s)
        GROUP BY fi.rutenummer;
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (rutenummers,))
        return {r["rutenummer"]: r.get("route_geometry") for r in cur.fetchall()}


def _route_total_lengths_and_names(conn, rutenummers: List[str]) -> Dict[str, Dict[str, Any]]:
    """rutenummer -> {total_length_m, rutenavn}.

    Length is summed from the route's links via the patched fotruteinfo view —
    so any rutenummer remap (ops.rutenummer_remap) is reflected. rutenavn
    falls back to the pre-patch stiflyt.routes.rutenavn for routes that
    Kartverket originally named, since the patched view doesn't carry a
    rutenavn override (yet — that's a future extension if needed).
    """
    if not rutenummers:
        return {}
    schema = os.getenv("ROUTE_SCHEMA", "stiflyt")
    if not validate_schema_name(schema):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {schema}")
    schema_quoted = quote_identifier(schema)
    from psycopg.rows import dict_row
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            WITH lengths AS (
                SELECT rl.rutenummer, SUM(rl.length_m) AS length_m
                FROM (
                    SELECT DISTINCT fi.rutenummer, l.link_id, l.length_m
                    FROM {FOTRUTEINFO_VIEW} fi
                    JOIN {schema_quoted}.link_segments ls ON ls.segment_id = fi.fotrute_fk
                    JOIN {schema_quoted}.links l ON l.link_id = ls.link_id
                    WHERE fi.rutenummer = ANY(%s)
                ) rl
                GROUP BY rl.rutenummer
            ),
            names AS (
                -- Pick any one rutenavn per remapped rutenummer (deterministic
                -- via MAX). Pre-existing rutenavn from stiflyt.routes is used
                -- as a fallback below.
                SELECT rutenummer, MAX(rutenavn) AS rutenavn
                FROM {FOTRUTEINFO_VIEW}
                WHERE rutenummer = ANY(%s) AND rutenavn IS NOT NULL
                GROUP BY rutenummer
            ),
            base AS (
                SELECT rutenummer, rutenavn AS legacy_navn FROM {schema_quoted}.routes
                WHERE rutenummer = ANY(%s)
            )
            SELECT
                COALESCE(l.rutenummer, b.rutenummer, n.rutenummer) AS rutenummer,
                l.length_m,
                COALESCE(n.rutenavn, b.legacy_navn) AS rutenavn
            FROM lengths l
            FULL OUTER JOIN base b USING (rutenummer)
            FULL OUTER JOIN names n USING (rutenummer);
            """,
            (rutenummers, rutenummers, rutenummers),
        )
        return {
            r["rutenummer"]: {
                "total_length_m": float(r["length_m"] or 0.0),
                "rutenavn": r.get("rutenavn"),
            }
            for r in cur.fetchall()
            if r.get("rutenummer")
        }


_RUTENAVN_SEPARATORS = (" - ", " – ", " — ")


def _parse_rutenavn_endpoints(rutenavn: Optional[str]) -> tuple:
    """'Skjolden - Arentzbu' -> ('Skjolden', 'Arentzbu'). Returns (None, None) otherwise.

    Most turrutebasen rutenavn follow the 'A - B' pattern (space-dash-space) for
    A↔B routes; some use the en-dash variant. We treat 'Ukjent' as no name.
    """
    if not rutenavn:
        return (None, None)
    s = rutenavn.strip()
    if not s or s.lower() == "ukjent":
        return (None, None)
    for sep in _RUTENAVN_SEPARATORS:
        if sep in s:
            a, _, b = s.partition(sep)
            a, b = a.strip(), b.strip()
            if a and b and a.lower() != "ukjent" and b.lower() != "ukjent":
                return (a, b)
            break
    return (None, None)


def _fetch_links_for_prefix_fast(conn, prefix: str) -> List[Dict[str, Any]]:
    """Filter-first replacement for services.signs._get_links_for_prefix.

    The stock `stiflyt.links_with_routes` view does a GROUP BY across the
    whole link/segment graph before any prefix filter can apply, so even
    a 78-row result takes ~700 ms. We push the prefix filter down to
    `fotruteinfo` first and only then aggregate.

    Returns the same shape: list of dicts with link_id, a_node, b_node,
    length_m, rutenummer_list. ~50 ms on bre instead of ~700 ms.
    """
    schema = os.getenv("ROUTE_SCHEMA", "stiflyt")
    if not validate_schema_name(schema):
        raise ValueError(f"Invalid ROUTE_SCHEMA: {schema}")
    schema_quoted = quote_identifier(schema)
    from psycopg.rows import dict_row
    # The rutenummer_list aggregation MUST filter to the area prefix too.
    # Otherwise a link shared between bre1 and (say) jot48 brings jot48 into
    # the report, and since jot48's other links aren't loaded, jot48 looks
    # like a 1-link route whose endpoints are interior bre1 nodes. The
    # endpoint detector then mis-classifies those nodes (see the anchor 71579
    # / Turtagrø case). Restricting rutenummer_list to the same prefix keeps
    # the per-route topology honest.
    sql = f"""
        WITH matched_links AS (
            SELECT DISTINCT ls.link_id
            FROM {schema_quoted}.link_segments ls
            JOIN {FOTRUTEINFO_VIEW} fi ON fi.fotrute_fk = ls.segment_id
            WHERE fi.rutenummer LIKE %s
        )
        SELECT
            l.link_id,
            l.a_node,
            l.b_node,
            l.length_m,
            array_agg(DISTINCT fi.rutenummer ORDER BY fi.rutenummer)
                FILTER (WHERE fi.rutenummer IS NOT NULL AND fi.rutenummer LIKE %s)
                AS rutenummer_list
        FROM matched_links m
        JOIN {schema_quoted}.links l USING (link_id)
        JOIN {schema_quoted}.link_segments ls USING (link_id)
        JOIN {FOTRUTEINFO_VIEW} fi ON fi.fotrute_fk = ls.segment_id
        GROUP BY l.link_id, l.a_node, l.b_node, l.length_m
        ORDER BY l.link_id;
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (f"{prefix}%", f"{prefix}%"))
        return [dict(r) for r in cur.fetchall()]


def _get_signs_bare_for_prefix(conn, prefix: str, *, timings: Optional[list] = None) -> Dict[str, Any]:
    """Lean version of services.signs.get_signs_for_prefix for the candidates flow.

    Skips the legacy _enrich_signs_with_sign_sites_and_route_km_multi enrichment,
    which runs ~41 single-route geometry queries (~40 s on bre). Also uses
    a faster filter-first links query. The new flow re-computes back_text /
    utm_coords / persisted status itself, so the enrichment is wasted work.
    Result: ~0.1 s instead of ~40 s.

    Phase timings are appended to `timings` if provided (Server-Timing).
    """
    _t = timings if timings is not None else []
    # 1. Links for the area (filter-first; fast)
    with phase_timer(_t, "links_query"):
        links = _fetch_links_for_prefix_fast(conn, prefix)

    routes = sorted({r for L in links for r in (L.get("rutenummer_list") or [])})

    # 2. Topology + names
    with phase_timer(_t, "anchor_nodes"):
        anchor_ids = sorted(
            {int(n) for L in links for n in (L.get("a_node"), L.get("b_node")) if n is not None}
        )
        anchor_nodes = _fetch_anchor_nodes(conn, anchor_ids)
    with phase_timer(_t, "anchor_names"):
        anchor_names = _resolve_anchor_names_for_prefix(conn, anchor_nodes, anchor_ids, routes)
    with phase_timer(_t, "compute_report"):
        report = compute_sign_report_from_links(links, anchor_nodes, anchor_names, sign_status={})
    report["scope"] = {"prefix": prefix, "routes": routes}

    # 3. Topology-aware destinations override (chain walk over each route).
    with phase_timer(_t, "build_chains"):
        route_links_by_route, route_endpoints_by_route = _build_route_topology(links)
        chain_by_route: Dict[str, Dict[int, Dict[str, Any]]] = {}
        for r, rls in route_links_by_route.items():
            eps = route_endpoints_by_route.get(r) or set()
            if not eps:
                continue
            chain_by_route[r] = _build_route_chain(rls, min(eps))
        all_route_endpoints = set()
        for r_eps in route_endpoints_by_route.values():
            all_route_endpoints.update(r_eps)
    report["_chain_by_route"] = chain_by_route

    with phase_timer(_t, "panels_per_sign"):
        for sign in report["signs"]:
            sign_node = sign.get("anchor_node_id")
            if sign_node is None:
                continue
            sign_routes = set(sign.get("rutenummer_list") or [])
            sign["destinations"] = _compute_panels_for_sign(
                sign_node, sign_routes, route_links_by_route, route_endpoints_by_route, anchor_names,
                chain_by_route=chain_by_route,
                all_route_endpoints=all_route_endpoints,
            )

    for sign in report["signs"]:
        coords = sign.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        sign["sign_site_id"] = None  # persisted overlay applied by sign_candidates
        sign["utm_coords"] = format_utm32v_block(lon, lat) if lon is not None and lat is not None else None
        sign.pop("route_km_by_route", None)
    return report


def get_sign_candidates_for_area(conn, area_code: str, *, timings: Optional[list] = None) -> Dict[str, Any]:
    """Return the candidate sign sites + panels for an area (e.g. 'bre').

    Reshapes the lean sign-report into the new-frontend spec and overlays
    persisted status from `ops.sign_sites`.

    Phase timings are appended to `timings` if provided (Server-Timing).
    """
    _t = timings if timings is not None else []
    report = _get_signs_bare_for_prefix(conn, area_code, timings=_t)
    with phase_timer(_t, "op_db_overlay"):
        with op_db_connection() as op_conn:
            correction_factor = get_distance_correction_factor(op_conn, area_code)
            persisted = get_sign_sites_status_by_area_anchor(op_conn, area_code)
            # Per-panel overrides, keyed by (sign_site_id, anchor_node_id)
            sign_site_ids = sorted({r["id"] for r in persisted.values() if r.get("id") is not None})
            overrides = get_sign_site_skilt_full(op_conn, sign_site_ids) if sign_site_ids else {}
            manual_sites = _fetch_manual_sites_for_area(op_conn, area_code)
            # Also fetch overrides for manual sites
            manual_site_ids = [m["id"] for m in manual_sites]
            manual_overrides = get_sign_site_skilt_full(op_conn, manual_site_ids) if manual_site_ids else {}
    sites_out: List[Dict[str, Any]] = []
    with phase_timer(_t, "anchor_sign_panels"):
        for sign in report.get("signs", []):
            coords = sign.get("coordinates") or [None, None]
            lon, lat = coords[0], coords[1]
            anchor_id = sign.get("anchor_node_id")
            name = sign.get("name")
            panels = _panels_from_sign(sign, correction_factor)
            # Status comes from ops.sign_sites if a row exists for this anchor in this area
            persisted_row = persisted.get(anchor_id) if anchor_id is not None else None
            if persisted_row:
                status = persisted_row.get("status") or "proposed"
                sign_site_id = persisted_row.get("id")
                site_code = persisted_row.get("site_code")
                site_overrides = overrides.get(sign_site_id, []) if sign_site_id is not None else []
                panels = _apply_panel_overrides(panels, site_overrides, correction_factor)
            else:
                status = "proposed"
                sign_site_id = sign.get("sign_site_id")
                site_code = None
            sites_out.append(
                {
                    "sign_site_id": sign_site_id,
                    "site_code": site_code,
                    "anchor_node_id": anchor_id,
                    "lon": lon,
                    "lat": lat,
                    "name": name,
                    "status": status,
                    "is_endpoint": sign.get("is_endpoint", False),
                    "is_junction": sign.get("is_junction", False),
                    "is_manual": False,
                    "rutenummer": None,
                    "route_numbers": list(sign.get("rutenummer_list") or []),
                    "back_text": format_sign_back(name, lon, lat),
                    "utm_coords": sign.get("utm_coords"),
                    "panels": panels,
                }
            )
    # Bulk-fetch endpoints + names for every distinct route the manual sites use,
    # so we don't issue a separate query per manual site (the legacy per-route
    # endpoint lookup is ~0.9 s on bre6).
    # Manual signs can belong to many routes (shared trail segments). Collect
    # every route in every manual site's list so we fetch endpoints + names once.
    with phase_timer(_t, "manual_endpoints"):
        manual_route_numbers = sorted({
            r
            for m in manual_sites
            for r in (m.get("rutenummer_list") or ([m["rutenummer"]] if m.get("rutenummer") else []))
            if r
        })
        if manual_route_numbers:
            endpoints_by_route = _route_endpoints_bulk(conn, manual_route_numbers)
            endpoint_anchor_ids = sorted({
                aid
                for ep in endpoints_by_route.values()
                for aid in (ep.get("first_a_node"), ep.get("last_b_node"))
                if aid is not None
            })
            with op_db_connection() as op_conn:
                endpoint_names = get_endpoint_names_for_anchors(op_conn, endpoint_anchor_ids) if endpoint_anchor_ids else {}
        else:
            endpoints_by_route = {}
            endpoint_names = {}

    # Reuse the chain_by_route built earlier in _get_signs_bare_for_prefix —
    # the same chain that anchor-based panels use, so distances are
    # consistent across both flavours of sign.
    chain_by_route_manual = report.pop("_chain_by_route", None) or {}

    # Append manual sites
    with phase_timer(_t, "manual_site_panels"):
        for m in manual_sites:
            lon, lat = m.get("lon"), m.get("lat")
            routes = list(m.get("rutenummer_list") or [])
            if not routes and m.get("rutenummer"):
                routes = [m["rutenummer"]]
            # For each route the manual sign is on, snap the click onto that
            # route's chain to get its 1-D position. Distance to each endpoint
            # is then just |snap_pos - endpoint_pos|.
            snap_pos_by_route: Dict[str, float] = {}
            # We also record one canonical route_km for the sign (the first route
            # in the list that snapped successfully).
            route_km_for_sign: Optional[float] = None
            if lon is not None and lat is not None:
                for r in routes:
                    chain = chain_by_route_manual.get(r)
                    if not chain:
                        continue
                    snap = _snap_to_route_chain(conn, float(lon), float(lat), r, chain)
                    if snap is None:
                        continue
                    snap_pos_by_route[r] = snap["pos_m"]
                    if route_km_for_sign is None:
                        route_km_for_sign = round(snap["pos_m"] / 1000.0, 4)
            panels = _manual_site_panels(
                routes, snap_pos_by_route, endpoints_by_route, chain_by_route_manual,
                endpoint_names, correction_factor,
            )
            site_overrides = manual_overrides.get(m["id"], [])
            panels = _apply_panel_overrides(panels, site_overrides, correction_factor)
            sites_out.append(
                {
                    "sign_site_id": m["id"],
                    "site_code": m.get("site_code"),
                    "anchor_node_id": None,
                    "lon": lon,
                    "lat": lat,
                    "name": m.get("name"),
                    "status": m.get("status") or "accepted",
                    "is_endpoint": False,
                    "is_junction": False,
                    "is_manual": True,
                    # `rutenummer` is the legacy primary route; frontend
                    # should prefer `route_numbers` for display.
                    "rutenummer": routes[0] if routes else None,
                    "route_numbers": routes,
                    # 1-D position along the primary route's chain (km from
                    # the smallest-id endpoint). Useful for ordering signs
                    # along a route or computing relative positions.
                    "route_km": route_km_for_sign,
                    "back_text": format_sign_back(m.get("name"), lon, lat),
                    "utm_coords": format_utm32v_block(lon, lat),
                    "panels": panels,
                }
            )
    # Collapse near-duplicate sign-sites that represent one physical place.
    # Two anchors merge iff their validated names match AND they're within
    # ~100 m. The first (smallest anchor_id) wins; secondaries are absorbed.
    with phase_timer(_t, "cluster_merge"):
        clusters = _cluster_sites_by_name_and_proximity(sites_out)
        if any(len(c) > 1 for c in clusters):
            merged: List[Dict[str, Any]] = []
            for c in clusters:
                merged.append(sites_out[c[0]] if len(c) == 1 else _merge_clustered_sites(sites_out, c))
            sites_out = merged

    counts: Dict[str, int] = {}
    for s in sites_out:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    return {
        "area_code": area_code,
        "sites": sites_out,
        "totals": {
            "total_sites": len(sites_out),
            "proposed": counts.get("proposed", 0),
            "accepted": counts.get("accepted", 0),
            "rejected": counts.get("rejected", 0),
            "installed": counts.get("installed", 0),
        },
        "scope": report.get("scope", {}),
    }
