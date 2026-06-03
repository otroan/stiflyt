"""Cultural-heritage (kulturminner) proximity queries.

Riksantikvaren's Askeladden register is imported by stiflyt-db into the same
database as the route data and exposed through stable views in the `stiflyt`
schema (migration 005): ``stiflyt.enkeltminne`` / ``lokalitet`` /
``sikringssone``. This service finds heritage monuments (``enkeltminne``) close
to a DNT route so the signs_app can warn maintainers about protected sites near
the trail. Geometry is EPSG:25833 (same as the link network), so ST_DWithin
works in metres with no reprojection.
"""
from typing import Any, Dict

from psycopg.rows import dict_row

from .database import ROUTE_SCHEMA, db_connection, quote_identifier, validate_schema_name


class KulturminneError(Exception):
    pass


def get_kulturminner_near_route(rutenummer: str, radius_m: float = 50.0, limit: int = 1000) -> Dict[str, Any]:
    """Heritage monuments within `radius_m` of a route's marked link network.

    Returns {rutenummer, radius_m, available, count, kulturminner:[...]}. Each
    item has navn, category/art, dating, protection type, a Kulturminnesøk
    link, distance in metres, a WGS84 centroid (lon/lat) and GeoJSON geometry.
    `available` is False when kulturminner hasn't been imported (no stable view).
    """
    if not isinstance(radius_m, (int, float)) or radius_m < 0 or radius_m > 5000:
        raise KulturminneError("radius_m must be between 0 and 5000")
    if not validate_schema_name(ROUTE_SCHEMA):
        raise KulturminneError(f"Invalid ROUTE_SCHEMA: {ROUTE_SCHEMA}")

    rs = quote_identifier(ROUTE_SCHEMA)

    with db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Graceful degradation when the dataset hasn't been imported yet.
            cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (f"{ROUTE_SCHEMA}.enkeltminne",))
            if not cur.fetchone()["present"]:
                return {"rutenummer": rutenummer, "radius_m": radius_m, "available": False, "count": 0, "kulturminner": []}

            cur.execute(
                f"""
                WITH route AS (
                    SELECT ST_Union(geom) AS geom
                    FROM {rs}.links_with_routes
                    WHERE %s = ANY(rutenummer_list)
                )
                SELECT
                    k.kulturminneid,
                    k.navn,
                    k.enkeltminnekategori AS kategori,
                    k.enkeltminneart      AS art,
                    k.datering,
                    k.vernetype,
                    k.linkkulturminnesok  AS link,
                    ST_Distance(k.omrade, route.geom)               AS distance_m,
                    ST_X(ST_Transform(ST_Centroid(k.omrade), 4326)) AS lon,
                    ST_Y(ST_Transform(ST_Centroid(k.omrade), 4326)) AS lat,
                    ST_AsGeoJSON(ST_Transform(k.omrade, 4326))::json AS geometry
                FROM {rs}.enkeltminne k, route
                WHERE route.geom IS NOT NULL
                  AND ST_DWithin(k.omrade, route.geom, %s)
                ORDER BY distance_m
                LIMIT %s;
                """,
                (rutenummer, float(radius_m), int(limit)),
            )
            rows = cur.fetchall()

    kulturminner = [
        {
            "kulturminneid": r.get("kulturminneid"),
            "navn": r.get("navn"),
            "kategori": r.get("kategori"),
            "art": r.get("art"),
            "datering": r.get("datering"),
            "vernetype": r.get("vernetype"),
            "link": r.get("link"),
            "distance_m": round(float(r["distance_m"]), 1) if r.get("distance_m") is not None else None,
            "lon": float(r["lon"]) if r.get("lon") is not None else None,
            "lat": float(r["lat"]) if r.get("lat") is not None else None,
            "geometry": r.get("geometry"),
        }
        for r in rows
    ]
    return {
        "rutenummer": rutenummer,
        "radius_m": radius_m,
        "available": True,
        "count": len(kulturminner),
        "kulturminner": kulturminner,
    }
