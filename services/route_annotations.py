"""Per-route annotations (rutebok diary, inspections, dugnad, work markers).

Single polymorphic table `ops.route_annotations` keyed on (area_code,
rutenummer). The `kind` column discriminates:

- diary               — rutebok-style free-text entry
- inspection          — inspection report
- dugnad              — dugnad report (summary of work done)
- work_klipping       — klipping/brush-clearing needed
- work_bridge         — bridge in disrepair / needed
- work_klopper        — klopper (planks) need replacement / new
- work_other          — generic "something needs doing"

`geom` is optional (Point in SRID 25833) — typically set for work_*
kinds so the marker renders on the map. `resolved_at` flips from
null → timestamp when the OK has dealt with the issue (used to filter
the map layer to only-open markers).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row

ALLOWED_KINDS = {
    "diary",
    "inspection",
    "dugnad",
    "work_klipping",
    "work_bridge",
    "work_klopper",
    "work_other",
}


def _row_to_api(r: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a DB row into the JSON the frontend expects.

    geom is decomposed into lon/lat (WGS84) so the client doesn't have to
    parse PostGIS hex; if the row has no geom, both are null.
    """
    out: Dict[str, Any] = {
        "id": r["id"],
        "area_code": r["area_code"],
        "rutenummer": r["rutenummer"],
        "kind": r["kind"],
        "position_along_m": r.get("position_along_m"),
        "title": r.get("title"),
        "body": r.get("body"),
        "occurred_at": r["occurred_at"].isoformat() if r.get("occurred_at") else None,
        "recorded_by": r.get("recorded_by"),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "resolved_at": r["resolved_at"].isoformat() if r.get("resolved_at") else None,
        "lon": r.get("lon"),
        "lat": r.get("lat"),
    }
    return out


_SELECT_BASE = """
    SELECT id, area_code, rutenummer, kind, position_along_m, title, body,
           occurred_at, recorded_by, created_at, resolved_at,
           CASE WHEN geom IS NULL THEN NULL
                ELSE ST_X(ST_Transform(geom, 4326)) END AS lon,
           CASE WHEN geom IS NULL THEN NULL
                ELSE ST_Y(ST_Transform(geom, 4326)) END AS lat
    FROM ops.route_annotations
"""


def list_for_route(
    op_conn,
    area_code: str,
    rutenummer: str,
    *,
    kinds: Optional[List[str]] = None,
    include_resolved: bool = True,
) -> List[Dict[str, Any]]:
    where = ["area_code = %s", "rutenummer = %s"]
    params: List[Any] = [area_code, rutenummer]
    if kinds:
        where.append("kind = ANY(%s)")
        params.append(list(kinds))
    if not include_resolved:
        where.append("resolved_at IS NULL")
    sql = _SELECT_BASE + " WHERE " + " AND ".join(where) + " ORDER BY occurred_at DESC, id DESC"
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [_row_to_api(r) for r in cur.fetchall()]


def list_work_markers_for_area(
    op_conn, area_code: str, *, include_resolved: bool = False
) -> List[Dict[str, Any]]:
    """Map-layer feed: every work_* marker in the area that has a geom.

    The signs_app renders these as point features on the map; resolved
    markers are hidden by default but the UI can flip include_resolved=true
    to show history.
    """
    where = ["area_code = %s", "kind LIKE 'work_%%'", "geom IS NOT NULL"]
    params: List[Any] = [area_code]
    if not include_resolved:
        where.append("resolved_at IS NULL")
    sql = _SELECT_BASE + " WHERE " + " AND ".join(where) + " ORDER BY occurred_at DESC"
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [_row_to_api(r) for r in cur.fetchall()]


def get(op_conn, annotation_id: int) -> Optional[Dict[str, Any]]:
    with op_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SELECT_BASE + " WHERE id = %s", (annotation_id,))
        r = cur.fetchone()
        return _row_to_api(dict(r)) if r else None


def insert(
    op_conn,
    *,
    area_code: str,
    rutenummer: str,
    kind: str,
    title: Optional[str] = None,
    body: Optional[str] = None,
    occurred_at: Optional[str] = None,
    position_along_m: Optional[float] = None,
    lon: Optional[float] = None,
    lat: Optional[float] = None,
    recorded_by: Optional[str] = None,
) -> Dict[str, Any]:
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"Unknown kind {kind!r}; allowed: {sorted(ALLOWED_KINDS)}")
    # geom is set from lon/lat (WGS84 → transformed to 25833 on the fly)
    has_geom = lon is not None and lat is not None
    geom_sql = "ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833)" if has_geom else "NULL"
    sql = f"""
        INSERT INTO ops.route_annotations
            (area_code, rutenummer, kind, title, body, occurred_at,
             position_along_m, geom, recorded_by)
        VALUES (%s, %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()),
                %s, {geom_sql}, %s)
        RETURNING id
    """
    params: List[Any] = [
        area_code, rutenummer, kind, title, body, occurred_at,
        position_along_m,
    ]
    if has_geom:
        params.extend([lon, lat])
    params.append(recorded_by)
    with op_conn.cursor() as cur:
        cur.execute(sql, params)
        new_id = cur.fetchone()[0]
    op_conn.commit()
    row = get(op_conn, new_id)
    if row is None:
        # Shouldn't happen — we just inserted.
        raise RuntimeError(f"Inserted annotation id={new_id} not retrievable")
    return row


_PATCHABLE_FIELDS = {"title", "body", "occurred_at", "position_along_m", "resolved_at", "kind"}


def update(op_conn, annotation_id: int, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if "kind" in patch and patch["kind"] not in ALLOWED_KINDS:
        raise ValueError(f"Unknown kind {patch['kind']!r}")
    sets: List[str] = []
    params: List[Any] = []
    for k in _PATCHABLE_FIELDS:
        if k in patch:
            sets.append(f"{k} = %s")
            params.append(patch[k])
    # geom can be patched via lon/lat — null lon clears the geom.
    if "lon" in patch or "lat" in patch:
        lon = patch.get("lon")
        lat = patch.get("lat")
        if lon is None or lat is None:
            sets.append("geom = NULL")
        else:
            sets.append("geom = ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833)")
            params.extend([lon, lat])
    if not sets:
        return get(op_conn, annotation_id)
    params.append(annotation_id)
    sql = f"UPDATE ops.route_annotations SET {', '.join(sets)} WHERE id = %s"
    with op_conn.cursor() as cur:
        cur.execute(sql, params)
        if cur.rowcount == 0:
            return None
    op_conn.commit()
    return get(op_conn, annotation_id)


def delete(op_conn, annotation_id: int) -> bool:
    with op_conn.cursor() as cur:
        cur.execute("DELETE FROM ops.route_annotations WHERE id = %s", (annotation_id,))
        deleted = cur.rowcount > 0
    op_conn.commit()
    return deleted
