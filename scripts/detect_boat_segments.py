"""Detect suspected boat/ferry tracks in turrutebasen.

Heuristic: a real footpath samples its geometry every ~10–30 m. A boat
crossing drawn as a straight-line "fotrute" has vertices hundreds of metres
apart — geometrically impossible for an on-the-ground trail. We flag fotruter
where:

    ST_Length(senterlinje) > MIN_LENGTH_M  AND
    Length / (ST_NPoints - 1) > MIN_M_PER_VERTEX  AND
    ST_NPoints < MAX_VERTS

Output is a Markdown table sorted by length descending. Use this to seed
`data/route_errata.yaml` and to compile a single Kartverket-bound report
covering every area (Femundsmarka, fjord crossings, Finnmark, Lofoten…).

Run:
    python -m scripts.detect_boat_segments
    python -m scripts.detect_boat_segments --area fem
    python -m scripts.detect_boat_segments --csv /tmp/boat_segments.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Dict

# Path bootstrap
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.database import get_db_connection  # noqa: E402

MIN_LENGTH_M = 1500
MIN_M_PER_VERTEX = 150
MAX_VERTS = 30


SQL = """
WITH suspects AS (
    SELECT
        f.objid AS fotrute_fk,
        f.lokalid,
        f.versjonid,
        ROUND(ST_Length(f.senterlinje)::numeric, 0) AS len_m,
        ST_NPoints(f.senterlinje) AS verts,
        ROUND(
            (ST_Length(f.senterlinje) / GREATEST(ST_NPoints(f.senterlinje) - 1, 1))::numeric,
            0
        ) AS m_per_vertex,
        ST_X(ST_Centroid(f.senterlinje))::int AS utm_cx,
        ST_Y(ST_Centroid(f.senterlinje))::int AS utm_cy,
        ST_AsText(ST_Transform(ST_Centroid(f.senterlinje), 4326)) AS wgs84_centroid,
        f.senterlinje AS geom
    FROM stiflyt.fotrute f
    WHERE ST_Length(f.senterlinje) > %s
      AND ST_NPoints(f.senterlinje) < %s
      AND ST_Length(f.senterlinje) / GREATEST(ST_NPoints(f.senterlinje) - 1, 1) > %s
)
SELECT
    s.fotrute_fk, s.lokalid, s.versjonid,
    s.len_m, s.verts, s.m_per_vertex,
    s.utm_cx, s.utm_cy,
    s.wgs84_centroid,
    (
        SELECT string_agg(DISTINCT fi.rutenummer, ',' ORDER BY fi.rutenummer)
        FROM stiflyt.fotruteinfo fi
        WHERE fi.fotrute_fk = s.fotrute_fk
    ) AS rutenummers,
    (
        SELECT string_agg(DISTINCT regexp_replace(fi.rutenummer, '[0-9].*$', ''), ',' ORDER BY regexp_replace(fi.rutenummer, '[0-9].*$', ''))
        FROM stiflyt.fotruteinfo fi
        WHERE fi.fotrute_fk = s.fotrute_fk
          AND fi.rutenummer ~ '^[a-z]+[0-9]'
    ) AS area_prefixes
FROM suspects s
ORDER BY s.len_m DESC;
"""


def detect(conn, area: str | None = None) -> List[Dict]:
    from psycopg.rows import dict_row
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SQL, (MIN_LENGTH_M, MAX_VERTS, MIN_M_PER_VERTEX))
        rows = [dict(r) for r in cur.fetchall()]
    if area:
        rows = [r for r in rows if r.get("area_prefixes") and area in r["area_prefixes"].split(",")]
    return rows


def print_markdown(rows: List[Dict]) -> None:
    if not rows:
        print("No suspected boat tracks found.")
        return
    print(f"\n{len(rows)} suspected boat track(s):\n")
    print("| fotrute_fk | length (m) | verts | m/vertex | area(s) | rutenummers | wgs84 centroid |")
    print("|---:|---:|---:|---:|---|---|---|")
    for r in rows:
        print(
            f"| {r['fotrute_fk']} "
            f"| {int(r['len_m']):,} "
            f"| {r['verts']} "
            f"| {int(r['m_per_vertex'])} "
            f"| {r.get('area_prefixes') or '—'} "
            f"| {r.get('rutenummers') or '—'} "
            f"| {r['wgs84_centroid']} |"
        )


def write_csv(rows: List[Dict], path: Path) -> None:
    if not rows:
        return
    fieldnames = [
        "fotrute_fk", "lokalid", "versjonid",
        "len_m", "verts", "m_per_vertex",
        "utm_cx", "utm_cy", "wgs84_centroid",
        "area_prefixes", "rutenummers",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})
    print(f"\nwrote {len(rows)} rows to {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area", help="filter by area prefix (e.g. fem)")
    parser.add_argument("--csv", type=Path, help="write a CSV report to this path")
    args = parser.parse_args()

    with get_db_connection() as conn:
        rows = detect(conn, area=args.area)
    print_markdown(rows)
    if args.csv:
        write_csv(rows, args.csv)


if __name__ == "__main__":
    main()
