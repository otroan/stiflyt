"""Report multi-route junctions and cross-area boundary candidates.

A multi-route junction is a graph node where >=2 distinct rutenummers
meet — a place where a hiker has to make a route-choice decision. The
existing anchor_nodes matview catches most of these (degree != 2 for
Y/X junctions on a single route, plus migration 010's route-boundary
anchors), but misses the case where local link-degree is 2 yet two
different routes share the node with a single link each side. This
script surfaces those.

Each junction is tagged with the set of owner areas its routes belong
to. A junction whose owner-area set has size >1 is a candidate
cross-area boundary post — see memory project-signs-cross-area-design.

Run:
    python -m scripts.junction_report
    python -m scripts.junction_report --area bre
    python -m scripts.junction_report --area bre --cross-area-only
    python -m scripts.junction_report --missing-from-anchor-nodes
    python -m scripts.junction_report --csv /tmp/junctions.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.database import get_db_connection  # noqa: E402
from services.junctions import detect_multi_route_junctions  # noqa: E402


def filter_rows(
    rows: List[Dict[str, Any]],
    *,
    area: str | None,
    cross_area_only: bool,
    missing_from_anchor_nodes: bool,
) -> List[Dict[str, Any]]:
    out = rows
    if area:
        out = [r for r in out if area in r["owner_areas"]]
    if cross_area_only:
        out = [r for r in out if r["is_cross_area"]]
    if missing_from_anchor_nodes:
        out = [r for r in out if not r["in_anchor_nodes"]]
    return out


def print_markdown(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        print("No multi-route junctions found.")
        return
    print(f"\n{len(rows)} multi-route junction(s):\n")
    print("| node_id | UTM 32V | routes | areas | deg | in anchors |")
    print("|---:|---|---|---|---:|:---:|")
    for r in rows:
        utm = f"{r['utm_x']},{r['utm_y']}"
        routes = ", ".join(r["rutenummers"])
        areas_str = ", ".join(r["owner_areas"])
        if r["is_cross_area"]:
            areas_str += " *"
        anc = (r["anchor_type"] or "—") if r["in_anchor_nodes"] else "no"
        print(
            f"| {r['node_id']} | {utm} | {routes} "
            f"| {areas_str} | {r['node_degree']} | {anc} |"
        )


def write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    fieldnames = [
        "node_id", "utm_x", "utm_y", "lon", "lat",
        "route_count", "rutenummers",
        "owner_areas", "is_cross_area",
        "node_degree", "in_anchor_nodes", "anchor_type",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            row = {k: r.get(k) for k in fieldnames}
            row["rutenummers"] = ",".join(r["rutenummers"])
            row["owner_areas"] = ",".join(r["owner_areas"])
            w.writerow(row)
    print(f"\nwrote {len(rows)} rows to {path}")


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--area", help="filter to junctions involving this area (e.g. bre)")
    p.add_argument(
        "--cross-area-only", action="store_true",
        help="only junctions whose routes span >1 area",
    )
    p.add_argument(
        "--missing-from-anchor-nodes", action="store_true",
        help="only junctions not currently in the anchor_nodes matview",
    )
    p.add_argument("--csv", type=Path, help="write a CSV report to this path")
    args = p.parse_args()

    with get_db_connection() as conn:
        rows = detect_multi_route_junctions(conn)
    rows = filter_rows(
        rows,
        area=args.area,
        cross_area_only=args.cross_area_only,
        missing_from_anchor_nodes=args.missing_from_anchor_nodes,
    )
    print_markdown(rows)
    if args.csv:
        write_csv(rows, args.csv)


if __name__ == "__main__":
    main()
