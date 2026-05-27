"""Graph helpers over the corrected route link-graph (ops.route_link_graph).

A route's links form an undirected multigraph on node ids. These helpers
compute connectivity/cyclomatic structure and decompose a looped route into
its parallel "arms" between fork nodes. Shared by RouteLoopValidator and the
link-exclusion API/UI so both agree on what an "arm" is.

A link dict is expected to have: link_id, a_node, b_node, length_m.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

# adjacency: node -> list of (neighbour_node, link_id, length_m)
Adjacency = Dict[int, List[Tuple[int, int, float]]]


def build_adjacency(links: List[Dict[str, Any]]) -> Adjacency:
    adj: Adjacency = defaultdict(list)
    for l in links:
        a, b = int(l["a_node"]), int(l["b_node"])
        lid = int(l["link_id"])
        length = float(l.get("length_m") or 0.0)
        adj[a].append((b, lid, length))
        adj[b].append((a, lid, length))
    return adj


def node_degrees(adj: Adjacency) -> Dict[int, int]:
    return {n: len(edges) for n, edges in adj.items()}


def connected_components(adj: Adjacency) -> int:
    seen: set = set()
    comps = 0
    for start in adj:
        if start in seen:
            continue
        comps += 1
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for nb, _lid, _len in adj[cur]:
                if nb not in seen:
                    stack.append(nb)
    return comps


def components(adj: Adjacency) -> List[set]:
    """Connected components as a list of node-id sets."""
    seen: set = set()
    out: List[set] = []
    for start in adj:
        if start in seen:
            continue
        comp: set = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.add(cur)
            for nb, _lid, _len in adj[cur]:
                if nb not in seen:
                    stack.append(nb)
        out.append(comp)
    return out


def route_connectivity(links: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Describe a route's connectivity.

    Returns:
        connected       — True iff the route's link graph is one component
        component_count — number of components
        components      — [{nodes: [...], endpoints: [...]}], largest first;
                          `endpoints` are the degree-1 nodes within that
                          component (the component's loose ends)
    """
    adj = build_adjacency(links)
    deg = node_degrees(adj)
    comps = components(adj)
    comps.sort(key=len, reverse=True)
    described = [
        {
            "nodes": sorted(c),
            "endpoints": sorted(n for n in c if deg.get(n, 0) == 1),
        }
        for c in comps
    ]
    return {
        "connected": len(comps) <= 1,
        "component_count": len(comps),
        "components": described,
    }


def cyclomatic_number(links: List[Dict[str, Any]]) -> int:
    """Number of independent cycles: E - N + C. 0 means the route is a forest
    (tree/chain), > 0 means at least one loop."""
    if not links:
        return 0
    adj = build_adjacency(links)
    return len(links) - len(adj) + connected_components(adj)


def _chains(adj: Adjacency) -> List[Dict[str, Any]]:
    """Maximal paths through degree-2 interior nodes, bounded by nodes of
    degree != 2 (forks/endpoints). Each chain is emitted once.

    Returns dicts: {endpoints:(a,b), links:[...], nodes:[a,...,b], length_m}.
    """
    deg = node_degrees(adj)
    junctions = [n for n, d in deg.items() if d != 2]
    seen_links: set = set()
    chains: List[Dict[str, Any]] = []
    for j in junctions:
        for (nb, lid, length) in adj[j]:
            if lid in seen_links:
                continue
            seen_links.add(lid)
            link_ids = [lid]
            nodes = [j, nb]
            total = length
            cur = nb
            while deg.get(cur, 0) == 2:
                nxt = None
                for (nn, ll, le) in adj[cur]:
                    if ll != link_ids[-1]:
                        nxt = (nn, ll, le)
                        break
                if nxt is None or nxt[1] in seen_links:
                    break
                nn, ll, le = nxt
                seen_links.add(ll)
                link_ids.append(ll)
                total += le
                nodes.append(nn)
                cur = nn
            chains.append({
                "endpoints": tuple(sorted((j, cur))),
                "links": link_ids,
                "nodes": nodes,
                "length_m": total,
            })
    return chains


def decompose_loops(links: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Describe a looped route's structure.

    Returns:
        cyclomatic   — number of independent cycles
        fork_nodes   — nodes with degree >= 3
        arm_groups   — [{endpoints:[a,b], arms:[{links, nodes, length_m}, ...]}]
                       one group per pair of fork nodes joined by >= 2 parallel
                       chains (i.e. a resolvable loop)
        decomposable — True iff every independent cycle is explained by a
                       parallel-arm group (the simple case the UI can resolve
                       arm-by-arm). False for pure cycles / nested loops, where
                       the UI must fall back to per-link selection.
    """
    result: Dict[str, Any] = {
        "cyclomatic": cyclomatic_number(links),
        "fork_nodes": [],
        "arm_groups": [],
        "decomposable": False,
    }
    if result["cyclomatic"] <= 0:
        return result

    adj = build_adjacency(links)
    deg = node_degrees(adj)
    result["fork_nodes"] = sorted(n for n, d in deg.items() if d >= 3)

    groups: Dict[Tuple[int, int], List[Dict[str, Any]]] = defaultdict(list)
    for ch in _chains(adj):
        groups[ch["endpoints"]].append(ch)

    arm_groups: List[Dict[str, Any]] = []
    explained_cycles = 0
    for endpoints, chs in groups.items():
        if len(chs) >= 2 and endpoints[0] != endpoints[1]:
            explained_cycles += len(chs) - 1
            arm_groups.append({
                "endpoints": list(endpoints),
                "arms": [
                    {"links": c["links"], "nodes": c["nodes"], "length_m": c["length_m"]}
                    for c in chs
                ],
            })
    result["arm_groups"] = arm_groups
    result["decomposable"] = bool(arm_groups) and explained_cycles == result["cyclomatic"]
    return result
