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


def list_tracks(op_conn, area_code: str) -> List[Dict[str, Any]]:
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, area_code, name, point_count, length_m, uploaded_by, uploaded_at,
                   ST_AsGeoJSON(ST_Transform(geom, 4326))::json AS geometry
            FROM ops.gpx_tracks
            WHERE area_code = %s
            ORDER BY uploaded_at DESC
            """,
            (area_code,),
        )
        return [_row_to_api(dict(r)) for r in cur.fetchall()]


def delete_track(op_conn, track_id: int) -> bool:
    with op_conn.cursor() as cur:
        cur.execute("DELETE FROM ops.gpx_tracks WHERE id = %s", (track_id,))
        deleted = cur.rowcount > 0
    op_conn.commit()
    return deleted
