"""Uploaded GPX tracks — the actually-walked overlay (Phase C).

Tracks are area-scoped and stored as MultiLineString in SRID 25833 (metres).
GPX is parsed with the stdlib (no extra dependency): we pull <trk>/<trkseg>/
<trkpt> and <rte>/<rtept> point sequences, ignoring elevation/time for the v1
overlay. Geometry is the only thing stored — not the raw file.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from psycopg.rows import dict_row

# A track segment is an ordered list of (lon, lat) WGS84 points.
Segment = List[Tuple[float, float]]


class GpxParseError(ValueError):
    pass


def parse_gpx(raw: bytes) -> Tuple[List[Segment], Optional[str]]:
    """Parse GPX bytes into (segments, name). Segments with <2 points are
    dropped. `name` is the first track/route/metadata name if present.

    Uses `{*}` wildcard namespace matching so GPX 1.0/1.1 (and odd exports) all
    work without hardcoding the namespace URI.
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise GpxParseError(f"Not valid GPX/XML: {e}") from e

    def _pts(parent, tag: str) -> Segment:
        out: Segment = []
        for p in parent.findall(f"{{*}}{tag}"):
            lon, lat = p.get("lon"), p.get("lat")
            if lon is None or lat is None:
                continue
            try:
                out.append((float(lon), float(lat)))
            except ValueError:
                continue
        return out

    segments: List[Segment] = []
    for trk in root.findall(".//{*}trk"):
        for seg in trk.findall("{*}trkseg"):
            pts = _pts(seg, "trkpt")
            if len(pts) >= 2:
                segments.append(pts)
    for rte in root.findall(".//{*}rte"):
        pts = _pts(rte, "rtept")
        if len(pts) >= 2:
            segments.append(pts)

    name: Optional[str] = None
    for path in (".//{*}trk/{*}name", ".//{*}metadata/{*}name", ".//{*}rte/{*}name"):
        el = root.find(path)
        if el is not None and (el.text or "").strip():
            name = el.text.strip()
            break

    if not segments:
        raise GpxParseError("GPX has no track/route with at least two points.")
    return segments, name


def _segments_to_wkt(segments: List[Segment]) -> str:
    parts = []
    for seg in segments:
        coords = ", ".join(f"{lon} {lat}" for lon, lat in seg)
        parts.append(f"({coords})")
    return "MULTILINESTRING(" + ", ".join(parts) + ")"


def _row_to_api(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "area_code": r["area_code"],
        "name": r.get("name"),
        "point_count": r.get("point_count"),
        "length_m": r.get("length_m"),
        "length_km": round(r["length_m"] / 1000.0, 1) if r.get("length_m") is not None else None,
        "uploaded_by": r.get("uploaded_by"),
        "uploaded_at": r["uploaded_at"].isoformat() if r.get("uploaded_at") else None,
        "geometry": r.get("geometry"),
    }


def insert_track(
    op_conn,
    *,
    area_code: str,
    name: Optional[str],
    segments: List[Segment],
    uploaded_by: Optional[str],
) -> Dict[str, Any]:
    wkt = _segments_to_wkt(segments)
    point_count = sum(len(s) for s in segments)
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO ops.gpx_tracks (area_code, name, geom, point_count, length_m, uploaded_by)
            VALUES (
                %s, %s,
                ST_Multi(ST_Transform(ST_GeomFromText(%s, 4326), 25833)),
                %s,
                ST_Length(ST_Transform(ST_GeomFromText(%s, 4326), 25833)),
                %s
            )
            RETURNING id, area_code, name, point_count, length_m, uploaded_by, uploaded_at,
                      ST_AsGeoJSON(ST_Transform(geom, 4326))::json AS geometry
            """,
            (area_code, name, wkt, point_count, wkt, uploaded_by),
        )
        row = cur.fetchone()
    op_conn.commit()
    return _row_to_api(dict(row))


def list_tracks(op_conn, area_code: str, *, simplify_m: float = 10.0) -> List[Dict[str, Any]]:
    # Simplify in source SRID (25833, metres) before reprojecting to WGS84 —
    # cuts the JSON payload an order of magnitude for typical walked tracks
    # without visible loss at map zooms. compare_to_route still queries the
    # full-resolution geom directly.
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, area_code, name, point_count, length_m, uploaded_by, uploaded_at,
                   ST_AsGeoJSON(ST_Transform(ST_Simplify(geom, %s), 4326))::json AS geometry
            FROM ops.gpx_tracks
            WHERE area_code = %s
            ORDER BY uploaded_at DESC
            """,
            (simplify_m, area_code),
        )
        return [_row_to_api(dict(r)) for r in cur.fetchall()]


def compare_to_route(conn, area_code: str, rutenummer: str, *, corridor_m: float = 30.0) -> Dict[str, Any]:
    """Compare uploaded GPX tracks to a route's mapped line.

    For every track in the area that follows the route (within a `corridor_m`
    corridor), measures *walked length vs mapped length over the shared span*:

      walked_m       = track length inside the route's corridor
      route_covered_m= route length inside the track's corridor (the shared span)
      factor         = walked_m / route_covered_m  (apples-to-apples, robust to
                       partial coverage)
      coverage_pct   = route_covered_m / route_len_m  (how much of the route the
                       track actually covers — factor is only trustworthy when
                       this is high)

    Tracks covering >= 30% of the route feed an aggregate `measured_factor`
    (Σwalked / Σcovered), the empirical signal that drove the default down from
    ×1.125 (historic) to ×1.05.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ST_Length(ST_Collect(geom)) FROM ops.route_link_graph WHERE rutenummer = %s",
            (rutenummer,),
        )
        row = cur.fetchone()
        route_len_m = row[0] if row else None

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH r AS (
                SELECT ST_Collect(geom) AS geom FROM ops.route_link_graph WHERE rutenummer = %s
            )
            SELECT
                t.id, t.name,
                ST_Length(ST_Intersection(t.geom, ST_Buffer(r.geom, %s))) AS walked_m,
                ST_Length(ST_Intersection(r.geom, ST_Buffer(t.geom, %s))) AS route_covered_m
            FROM ops.gpx_tracks t, r
            WHERE t.area_code = %s
              AND r.geom IS NOT NULL
              AND ST_DWithin(t.geom, r.geom, %s)
            ORDER BY route_covered_m DESC
            """,
            (rutenummer, corridor_m, corridor_m, area_code, corridor_m),
        )
        rows = [dict(r) for r in cur.fetchall()]

    tracks: List[Dict[str, Any]] = []
    for r in rows:
        covered = r["route_covered_m"] or 0.0
        walked = r["walked_m"] or 0.0
        rlen = route_len_m or 0.0
        tracks.append({
            "track_id": r["id"],
            "name": r["name"],
            "walked_m": round(walked, 1),
            "route_covered_m": round(covered, 1),
            "coverage_pct": round(covered / rlen * 100, 1) if rlen else None,
            "factor": round(walked / covered, 3) if covered > 0 else None,
        })

    used = [t for t in tracks if (t["coverage_pct"] or 0) >= 30.0 and t["route_covered_m"] > 0]
    sum_walked = sum(t["walked_m"] for t in used)
    sum_covered = sum(t["route_covered_m"] for t in used)
    measured_factor = round(sum_walked / sum_covered, 3) if sum_covered > 0 else None

    return {
        "rutenummer": rutenummer,
        "route_len_m": round(route_len_m, 1) if route_len_m else None,
        "corridor_m": corridor_m,
        "tracks": tracks,
        "measured_factor": measured_factor,
        "n_tracks_used": len(used),
    }


def delete_track(op_conn, track_id: int) -> bool:
    with op_conn.cursor() as cur:
        cur.execute("DELETE FROM ops.gpx_tracks WHERE id = %s", (track_id,))
        deleted = cur.rowcount > 0
    op_conn.commit()
    return deleted
