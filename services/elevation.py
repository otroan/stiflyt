"""Per-route elevation profiles from Kartverket Høydedata.

Samples the route's (corrected) vertices against the Kartverket /punkt REST API
(dtm1 — 1 m terrain model), batching up to 50 points/call, and caches the
assembled profile in ops.route_elevation_cache keyed on rutenummer + a checksum
of the sampled vertex list (so corrections that change the route shape
invalidate it). ~2.7 s per route on a cache miss; instant on a hit.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from psycopg.rows import dict_row

PUNKT_URL = "https://ws.geonorge.no/hoydedata/v1/punkt"
CHUNK = 50               # API max points per call
KOORDSYS = 25833
USER_AGENT = "stiflyt-signs-app/1.0 (DNT route maintenance; +https://github.com/)"

Vertex = Tuple[float, float]  # (east, north) in EPSG:25833


def _fetch_vertices(conn, rutenummer: str) -> List[Vertex]:
    """Ordered (east, north) vertices of the route's corrected geometry."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH g AS (
                SELECT ST_LineMerge(ST_Collect(geom)) AS geom
                FROM ops.route_link_graph WHERE rutenummer = %s
            ),
            d AS (SELECT (ST_DumpPoints(geom)).path AS path,
                         (ST_DumpPoints(geom)).geom AS p FROM g)
            SELECT ST_X(p), ST_Y(p) FROM d ORDER BY path
            """,
            (rutenummer,),
        )
        return [(round(r[0], 2), round(r[1], 2)) for r in cur.fetchall()]


def _checksum(vertices: List[Vertex]) -> str:
    h = hashlib.md5()
    h.update(repr(vertices).encode("utf-8"))
    return h.hexdigest()


def _fetch_elevations(vertices: List[Vertex]) -> Tuple[List[Optional[float]], Optional[str]]:
    """z (metres) for each vertex via batched /punkt calls; preserves order."""
    zs: List[Optional[float]] = []
    datakilde: Optional[str] = None
    for i in range(0, len(vertices), CHUNK):
        chunk = vertices[i:i + CHUNK]
        punkter = json.dumps([[e, n] for (e, n) in chunk])
        q = urllib.parse.urlencode({"koordsys": KOORDSYS, "punkter": punkter, "geojson": "false"})
        req = urllib.request.Request(f"{PUNKT_URL}?{q}", headers={"User-Agent": USER_AGENT})
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.load(r)
                break
            except Exception as e:  # transient network / 5xx — back off and retry
                last_err = e
                time.sleep(0.5 * (attempt + 1))
        else:
            raise RuntimeError(f"Kartverket /punkt failed after retries: {last_err}")
        for p in data.get("punkter", []):
            zs.append(p.get("z"))
            datakilde = datakilde or p.get("datakilde")
    return zs, datakilde


def _build_profile(vertices: List[Vertex], zs: List[Optional[float]]) -> Dict[str, Any]:
    """Cumulative-distance profile + 2D/3D length, ascent/descent, min/max."""
    samples: List[List[float]] = []
    dist = 0.0
    length_3d = 0.0
    ascent = 0.0
    descent = 0.0
    prev: Optional[Tuple[float, float, Optional[float]]] = None  # (e, n, z)
    for (e, n), z in zip(vertices, zs):
        if prev is not None:
            d2 = math.hypot(e - prev[0], n - prev[1])
            dist += d2
            if z is not None and prev[2] is not None:
                dz = z - prev[2]
                length_3d += math.hypot(d2, dz)
                if dz > 0:
                    ascent += dz
                else:
                    descent += -dz
            else:
                length_3d += d2
        samples.append([round(dist, 1), round(z, 1) if z is not None else None])
        prev = (e, n, z)
    zs_valid = [z for z in zs if z is not None]
    return {
        "samples": samples,
        "point_count": len(vertices),
        "length_2d_m": round(dist, 1),
        "length_3d_m": round(length_3d, 1),
        "ascent_m": round(ascent, 1),
        "descent_m": round(descent, 1),
        "min_z": round(min(zs_valid), 1) if zs_valid else None,
        "max_z": round(max(zs_valid), 1) if zs_valid else None,
    }


def _row_to_api(r: Dict[str, Any]) -> Dict[str, Any]:
    samples = r["samples"]
    if isinstance(samples, str):
        samples = json.loads(samples)
    return {
        "rutenummer": r["rutenummer"],
        "samples": samples,
        "point_count": r.get("point_count"),
        "length_2d_m": r.get("length_2d_m"),
        "length_3d_m": r.get("length_3d_m"),
        "ascent_m": r.get("ascent_m"),
        "descent_m": r.get("descent_m"),
        "min_z": r.get("min_z"),
        "max_z": r.get("max_z"),
        "datakilde": r.get("datakilde"),
        "sampled_at": r["sampled_at"].isoformat() if r.get("sampled_at") else None,
    }


def _resolve_endpoint_names(conn, rutenummer: str) -> Tuple[Optional[str], Optional[str]]:
    """Names at the first/last vertex of the route's merged geometry — same
    orientation _fetch_vertices uses, so they line up with the elevation
    chart's x=0 / x=max. Matches `ops.endpoint_names.geom` to the exact
    endpoint point (0.5 m tolerance for FP drift).
    """
    sql = """
        WITH g AS (
            SELECT ST_LineMerge(ST_Collect(geom)) AS geom
              FROM ops.route_link_graph WHERE rutenummer = %s
        )
        SELECT
          (SELECT name FROM ops.endpoint_names
            WHERE ST_DWithin(geom, (SELECT ST_StartPoint(geom) FROM g), 0.5)
            ORDER BY (rutenummer = %s) DESC NULLS LAST
            LIMIT 1) AS start_name,
          (SELECT name FROM ops.endpoint_names
            WHERE ST_DWithin(geom, (SELECT ST_EndPoint(geom) FROM g), 0.5)
            ORDER BY (rutenummer = %s) DESC NULLS LAST
            LIMIT 1) AS end_name
    """
    with conn.cursor() as cur:
        cur.execute(sql, (rutenummer, rutenummer, rutenummer))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


def get_elevation(conn, rutenummer: str, *, refresh: bool = False) -> Optional[Dict[str, Any]]:
    """Return the route's elevation profile, computing + caching on miss.

    `conn` must see both ops.route_link_graph (vertices) and
    ops.route_elevation_cache (cache) — same DB. Returns None for a route with
    no geometry.
    """
    vertices = _fetch_vertices(conn, rutenummer)
    if not vertices:
        return None
    checksum = _checksum(vertices)

    start_name, end_name = _resolve_endpoint_names(conn, rutenummer)

    if not refresh:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM ops.route_elevation_cache WHERE rutenummer = %s AND geom_checksum = %s",
                (rutenummer, checksum),
            )
            row = cur.fetchone()
            if row:
                out = _row_to_api(dict(row))
                out["cached"] = True
                out["start_name"] = start_name
                out["end_name"] = end_name
                return out

    zs, datakilde = _fetch_elevations(vertices)
    profile = _build_profile(vertices, zs)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ops.route_elevation_cache
                (rutenummer, geom_checksum, samples, point_count, length_2d_m,
                 length_3d_m, ascent_m, descent_m, min_z, max_z, datakilde, sampled_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (rutenummer) DO UPDATE SET
                geom_checksum = EXCLUDED.geom_checksum,
                samples = EXCLUDED.samples,
                point_count = EXCLUDED.point_count,
                length_2d_m = EXCLUDED.length_2d_m,
                length_3d_m = EXCLUDED.length_3d_m,
                ascent_m = EXCLUDED.ascent_m,
                descent_m = EXCLUDED.descent_m,
                min_z = EXCLUDED.min_z,
                max_z = EXCLUDED.max_z,
                datakilde = EXCLUDED.datakilde,
                sampled_at = NOW()
            """,
            (
                rutenummer, checksum, json.dumps(profile["samples"]), profile["point_count"],
                profile["length_2d_m"], profile["length_3d_m"], profile["ascent_m"],
                profile["descent_m"], profile["min_z"], profile["max_z"], datakilde,
            ),
        )
    conn.commit()
    out = {
        "rutenummer": rutenummer,
        "datakilde": datakilde,
        "cached": False,
        "start_name": start_name,
        "end_name": end_name,
        **profile,
    }
    return out
