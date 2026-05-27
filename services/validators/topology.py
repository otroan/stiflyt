"""Topology validators for route validation."""

from typing import Any, Dict, List

from psycopg.rows import dict_row

from .base import BaseValidator, ValidationResult, ValidationIssue, Severity
from ..route_topology import decompose_loops, route_connectivity


def _fetch_route_links(conn, rutenummer: str) -> List[Dict[str, Any]]:
    """The route's corrected link graph (remaps + exclusions already applied)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT link_id, a_node, b_node, length_m
            FROM ops.route_link_graph
            WHERE rutenummer = %s
            """,
            (rutenummer,),
        )
        return [dict(r) for r in cur.fetchall()]


def _node_coords(conn, node_ids: List[int]) -> Dict[int, tuple]:
    """node_id -> (x, y) in the route SRID (25833, metres)."""
    if not node_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT node_id, ST_X(geom), ST_Y(geom) FROM stiflyt.nodes WHERE node_id = ANY(%s)",
            ([int(n) for n in node_ids],),
        )
        return {int(r[0]): (float(r[1]), float(r[2])) for r in cur.fetchall()}


def _min_gap_pair(coords: Dict[int, tuple], comp_a: List[int], comp_b: List[int]) -> tuple:
    """(distance_m, a_node, b_node) for the closest node pair across two
    components — the node pair a bridge would connect."""
    best = (float("inf"), None, None)
    for na in comp_a:
        pa = coords.get(na)
        if not pa:
            continue
        for nb in comp_b:
            pb = coords.get(nb)
            if not pb:
                continue
            d = ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2) ** 0.5
            if d < best[0]:
                best = (d, na, nb)
    return best


def _bridge_suggestions(conn, comps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For each component after the first, the closest node pair to any
    already-seen component — i.e. the bridge that would attach it. For a chain
    A—B—C this yields the two small consecutive gaps, not the (large) A–C span.
    Each suggestion: {a_node, b_node, gap_m} with a_node < b_node."""
    coords = _node_coords(conn, [n for c in comps for n in c["nodes"]])
    out: List[Dict[str, Any]] = []
    for i in range(1, len(comps)):
        best = (float("inf"), None, None)
        for j in range(i):
            cand = _min_gap_pair(coords, comps[i]["nodes"], comps[j]["nodes"])
            if cand[0] < best[0]:
                best = cand
        gap, na, nb = best
        if na is None or nb is None:
            continue
        lo, hi = sorted((int(na), int(nb)))
        out.append({"a_node": lo, "b_node": hi, "gap_m": gap})
    return out


class RouteLoopValidator(BaseValidator):
    """Flags routes whose corrected link graph still contains a cycle.

    A loop means the route has parallel arms between two fork nodes — usually a
    turrutebasen variant that should be one path (resolve by excluding the wrong
    arm's links via the link-exclusion correction) or a genuine round-trip that
    should be split into separate rutenummer. Either way the sign blade-walk
    cannot pick an arm deterministically, so this is an error.
    """

    def get_name(self) -> str:
        return "route_loop"

    def get_category(self) -> str:
        return "topology"

    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        rutenummer = route_data.get("rutenummer")
        result = ValidationResult(rutenummer)

        links = _fetch_route_links(conn, rutenummer)
        if not links:
            return result

        info = decompose_loops(links)
        if info["cyclomatic"] <= 0:
            return result

        arm_links = sorted({
            lid
            for grp in info["arm_groups"]
            for arm in grp["arms"]
            for lid in arm["links"]
        })

        if info["decomposable"]:
            n_arms = sum(len(g["arms"]) for g in info["arm_groups"])
            message = (
                f"Ruta har en sløyfe: {n_arms} parallelle armer mellom "
                f"knutepunkt {info['fork_nodes']}. Velg hvilken arm som er den "
                f"reelle ruta og ekskluder den/de andre."
            )
        else:
            message = (
                f"Ruta har {info['cyclomatic']} sløyfe(r) som ikke kan deles "
                f"automatisk i armer (nøstede sløyfer eller ren rundtur). "
                f"Må vurderes manuelt."
            )

        result.add_issue(ValidationIssue(
            type="ROUTE_HAS_LOOP",
            message=message,
            severity=Severity.ERROR,
            affected_links=arm_links,
            metadata={
                "cyclomatic": info["cyclomatic"],
                "fork_nodes": info["fork_nodes"],
                "arm_groups": info["arm_groups"],
                "decomposable": info["decomposable"],
            },
        ))
        return result


class RouteDisconnectedValidator(BaseValidator):
    """Flags routes whose corrected link graph splits into >1 component.

    Disconnected components mean there's no continuous path along the route, so
    along-route distances cannot be computed across the gap — the endpoint
    detector would otherwise pick two unconnected nodes and report a bogus
    distance. Small gaps (typically a few metres) are digitizing artifacts that
    should be bridged; large ones may be genuinely separate trails sharing a
    rutenummer. Either way a human must resolve it before signs are generated,
    so this is an error.
    """

    def get_name(self) -> str:
        return "route_disconnected"

    def get_category(self) -> str:
        return "topology"

    def validate(self, route_data: Dict[str, Any], conn) -> ValidationResult:
        rutenummer = route_data.get("rutenummer")
        result = ValidationResult(rutenummer)

        links = _fetch_route_links(conn, rutenummer)
        if not links:
            return result

        conn_info = route_connectivity(links)
        if conn_info["connected"]:
            return result

        comps = conn_info["components"]
        # Per-gap bridge suggestions (nearest cross-component node pair). Small
        # gaps are digitizing artifacts; large ones may be separate trails.
        suggestions = _bridge_suggestions(conn, comps)
        gap_txt = ", ".join(f"{s['gap_m']:.0f} m" for s in sorted(suggestions, key=lambda s: s["gap_m"])) if suggestions else "?"

        message = (
            f"Ruta er usammenhengende: {conn_info['component_count']} adskilte deler. "
            f"Brudd å koble sammen: {gap_txt}. "
            f"Avstander langs ruta kan ikke beregnes over bruddet — koble sammen "
            f"delene (små brudd er digitaliseringsfeil) eller del opp i egne rutenummer."
        )

        result.add_issue(ValidationIssue(
            type="ROUTE_DISCONNECTED",
            message=message,
            severity=Severity.ERROR,
            metadata={
                "component_count": conn_info["component_count"],
                "components": comps,
                "bridge_suggestions": suggestions,
            },
        ))
        return result
