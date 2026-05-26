"""Detect distinct nodes that sit on top of each other in turrutebasen.

When Kartverket digitizes two abutting fotrute segments, their endpoints
should snap to the same coordinate. If they differ by even a millimetre,
the link-builder produces TWO distinct nodes (the table uses an exact
geom_hash unique constraint, so 0.085 m apart = two rows). Every such pair
is a "ghost endpoint" on the map: the trail visually continues but
topologically dead-ends, generating spurious 0-panel sign candidates.

Heuristic: two distinct node ids whose geometries are within MAX_DIST
meters of each other. We pair-up symmetrically and keep one row per pair.

Run:
    python -m scripts.detect_node_snap_errors
    python -m scripts.detect_node_snap_errors --area fem
    python -m scripts.detect_node_snap_errors --csv /tmp/node_snap.csv
    python -m scripts.detect_node_snap_errors --max-dist 1.0
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Dict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.database import get_db_connection  # noqa: E402

MAX_DIST_DEFAULT = 5.0  # metres


SQL_PAIRS = """
-- Endpoints first (46k vs 135k total) — interior vertices don't produce
-- "ghost endpoint" sign candidates so we ignore them.
WITH endpoint_nodes AS (
    SELECT DISTINCT n.node_id, n.geom
    FROM stiflyt.nodes n
    WHERE EXISTS (
        SELECT 1 FROM stiflyt.links l
        WHERE l.a_node = n.node_id OR l.b_node = n.node_id
    )
),
pairs AS (
    SELECT
        n1.node_id AS node_a, n2.node_id AS node_b,
        ST_Distance(n1.geom, n2.geom) AS dist_m,
        ST_Centroid(ST_Collect(n1.geom, n2.geom)) AS centre
    FROM endpoint_nodes n1
    JOIN endpoint_nodes n2 ON n2.node_id > n1.node_id
    WHERE ST_DWithin(n1.geom, n2.geom, %s)
)
SELECT
    node_a, node_b,
    ROUND(dist_m::numeric, 3) AS dist_m,
    ST_X(centre)::int AS utm_cx, ST_Y(centre)::int AS utm_cy,
    ST_AsText(ST_Transform(centre, 4326)) AS wgs84_centroid
FROM pairs
ORDER BY dist_m, node_a;
"""


SQL_NODE_INFO = """
-- Bulk lookup of (rutenummers, lokalids) per endpoint node.
SELECT
    node_id,
    string_agg(DISTINCT rutenummer, ',' ORDER BY rutenummer) FILTER (WHERE rutenummer IS NOT NULL) AS rutenummers,
    string_agg(DISTINCT lokalid,    ',' ORDER BY lokalid)    FILTER (WHERE lokalid    IS NOT NULL) AS lokalids
FROM (
    SELECT l.a_node AS node_id, fi.rutenummer, f.lokalid
    FROM stiflyt.links l
    JOIN stiflyt.link_segments ls ON ls.link_id = l.link_id
    JOIN stiflyt.fotrute      f  ON f.objid     = ls.segment_id
    JOIN stiflyt.fotruteinfo  fi ON fi.fotrute_fk = ls.segment_id
    WHERE l.a_node = ANY(%s)
    UNION ALL
    SELECT l.b_node AS node_id, fi.rutenummer, f.lokalid
    FROM stiflyt.links l
    JOIN stiflyt.link_segments ls ON ls.link_id = l.link_id
    JOIN stiflyt.fotrute      f  ON f.objid     = ls.segment_id
    JOIN stiflyt.fotruteinfo  fi ON fi.fotrute_fk = ls.segment_id
    WHERE l.b_node = ANY(%s)
) x
GROUP BY node_id;
"""


def detect(conn, max_dist: float, area: str | None = None) -> List[Dict]:
    import re
    from psycopg.rows import dict_row
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SQL_PAIRS, (max_dist,))
        pairs = [dict(r) for r in cur.fetchall()]
        if not pairs:
            return []
        node_ids = sorted({r["node_a"] for r in pairs} | {r["node_b"] for r in pairs})
        cur.execute(SQL_NODE_INFO, (node_ids, node_ids))
        per_node: Dict[int, Dict] = {r["node_id"]: dict(r) for r in cur.fetchall()}

    out: List[Dict] = []
    for p in pairs:
        a_info = per_node.get(p["node_a"], {})
        b_info = per_node.get(p["node_b"], {})
        rutes_a = (a_info.get("rutenummers") or "").split(",")
        rutes_b = (b_info.get("rutenummers") or "").split(",")
        all_rutes = sorted({r for r in rutes_a + rutes_b if r})
        prefixes = sorted({m.group(0) for r in all_rutes for m in [re.match(r"^[a-z]+", r)] if m})
        if area and area not in prefixes:
            continue
        out.append({
            **p,
            "rutenummers": ",".join(all_rutes),
            "area_prefixes": ",".join(prefixes),
            "lokalids_a": a_info.get("lokalids"),
            "lokalids_b": b_info.get("lokalids"),
        })
    return out


def print_markdown(rows: List[Dict]) -> None:
    if not rows:
        print("No near-duplicate node pairs found.")
        return
    print(f"\n{len(rows)} near-duplicate node pair(s):\n")
    print("| dist (m) | nodes | area(s) | rutenummers | wgs84 centroid |")
    print("|---:|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['dist_m']} "
            f"| {r['node_a']} ↔ {r['node_b']} "
            f"| {r.get('area_prefixes') or '—'} "
            f"| {r.get('rutenummers') or '—'} "
            f"| {r['wgs84_centroid']} |"
        )


def write_csv(rows: List[Dict], path: Path) -> None:
    if not rows:
        return
    fieldnames = [
        "node_a", "node_b", "dist_m",
        "utm_cx", "utm_cy", "wgs84_centroid",
        "area_prefixes", "rutenummers",
        "lokalids_a", "lokalids_b",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})
    print(f"\nwrote {len(rows)} rows to {path}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--max-dist", type=float, default=MAX_DIST_DEFAULT,
                   help=f"max distance in metres (default: {MAX_DIST_DEFAULT})")
    p.add_argument("--area", help="filter by area prefix (e.g. fem)")
    p.add_argument("--csv", type=Path, help="write a CSV report to this path")
    args = p.parse_args()

    with get_db_connection() as conn:
        rows = detect(conn, args.max_dist, area=args.area)
    print_markdown(rows)
    if args.csv:
        write_csv(rows, args.csv)


if __name__ == "__main__":
    main()
