"""Route service for processing routes and matrikkelenhet."""
import psycopg2
from psycopg2.extras import RealDictCursor
from .database import get_db_connection, ROUTE_SCHEMA, TEIG_SCHEMA


def format_matrikkelenhet(kommunenummer, gardsnummer, bruksnummer, festenummer=None):
    """Format matrikkelenhet as kommunenummer-gardsnummer/bruksnummer/festenummer."""
    if not kommunenummer:
        return None

    # Check if umatrikulert (gardsnummer=0 or bruksnummer=0)
    if gardsnummer == 0 or bruksnummer == 0:
        return f"{kommunenummer}-Umatrikulert"

    if gardsnummer is None or bruksnummer is None:
        return None

    # Format as kommunenummer-gardsnummer/bruksnummer/festenummer
    formatted = f"{kommunenummer}-{gardsnummer}/{bruksnummer}"
    if festenummer is not None and festenummer != 0:
        formatted += f"/{festenummer}"

    return formatted


def get_route_segments(conn, rutenummer):
    """Get all segments for a route."""
    query = f"""
        SELECT
            f.objid,
            f.senterlinje,
            fi.rutenummer,
            fi.rutenavn,
            fi.vedlikeholdsansvarlig
        FROM {ROUTE_SCHEMA}.fotrute f
        JOIN {ROUTE_SCHEMA}.fotruteinfo fi ON fi.fotrute_fk = f.objid
        WHERE fi.rutenummer = %s
        ORDER BY f.objid;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (rutenummer,))
        return cur.fetchall()


def combine_route_geometry(conn, segments):
    """Combine route segments into a single linestring."""
    if not segments:
        return None

    # Collect all geometries
    query = f"""
        SELECT ST_LineMerge(ST_Collect(senterlinje::geometry))::geometry as combined_geom
        FROM {ROUTE_SCHEMA}.fotrute
        WHERE objid = ANY(%s);
    """

    segment_ids = [seg['objid'] for seg in segments]

    with conn.cursor() as cur:
        cur.execute(query, (segment_ids,))
        result = cur.fetchone()
        return result[0] if result else None


def get_route_length(conn, route_geom):
    """Get route length in meters."""
    query = """
        SELECT ST_Length(ST_Transform(%s::geometry, 3857)) as length_meters;
    """

    with conn.cursor() as cur:
        cur.execute(query, (route_geom,))
        result = cur.fetchone()
        return result[0] if result else 0.0


def geometry_to_geojson(conn, geom):
    """Convert PostGIS geometry to GeoJSON."""
    query = """
        SELECT ST_AsGeoJSON(ST_Transform(%s::geometry, 4326)) as geojson;
    """

    with conn.cursor() as cur:
        cur.execute(query, (geom,))
        result = cur.fetchone()
        if result and result[0]:
            import json
            return json.loads(result[0])
        return None


def find_matrikkelenhet_intersections(conn, route_geom):
    """Find all intersections between route and teig polygons."""
    query = f"""
        SELECT
            t.matrikkelnummertekst,
            t.kommunenummer,
            t.kommunenavn,
            t.arealmerknadtekst,
            t.lagretberegnetareal,
            t.teigid,
            m.bruksnavn,
            m.gardsnummer,
            m.bruksnummer,
            m.festenummer,
            ST_Intersection(t.omrade::geometry, %s::geometry) as intersection_geom,
            ST_Length(ST_Transform(ST_Intersection(t.omrade::geometry, %s::geometry), 3857)) as length_meters
        FROM {TEIG_SCHEMA}.teig t
        LEFT JOIN {TEIG_SCHEMA}.matrikkelenhet m ON m.teig_fk = t.teigid
        WHERE ST_Intersects(t.omrade::geometry, %s::geometry)
        AND ST_GeometryType(ST_Intersection(t.omrade::geometry, %s::geometry)) IN ('ST_LineString', 'ST_MultiLineString');
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (route_geom, route_geom, route_geom, route_geom))
        return cur.fetchall()


def calculate_offsets(conn, route_geom, intersections, total_length):
    """Calculate offset from start for each intersection."""
    results = []

    for intersection in intersections:
        # Handle both LineString and MultiLineString
        # For MultiLineString, get the start point of the first line
        query = """
            SELECT ST_LineLocatePoint(
                %s::geometry,
                ST_StartPoint(
                    CASE
                        WHEN ST_GeometryType(%s::geometry) = 'ST_MultiLineString'
                        THEN ST_GeometryN(%s::geometry, 1)
                        ELSE %s::geometry
                    END
                )
            ) as fraction;
        """

        with conn.cursor() as cur:
            cur.execute(query, (route_geom, intersection['intersection_geom'],
                              intersection['intersection_geom'], intersection['intersection_geom']))
            result = cur.fetchone()
            fraction = result[0] if result else 0.0

        offset_meters = fraction * total_length
        offset_km = offset_meters / 1000.0

        # Format matrikkelenhet
        formatted_matrikkel = format_matrikkelenhet(
            intersection['kommunenummer'],
            intersection.get('gardsnummer'),
            intersection.get('bruksnummer'),
            intersection.get('festenummer')
        )

        results.append({
            'matrikkelenhet': formatted_matrikkel or intersection['matrikkelnummertekst'],
            'bruksnavn': intersection.get('bruksnavn'),
            'kommunenummer': intersection['kommunenummer'],
            'kommunenavn': intersection['kommunenavn'],
            'offset_meters': offset_meters,
            'offset_km': offset_km,
            'length_meters': intersection['length_meters'],
            'length_km': intersection['length_meters'] / 1000.0
        })

    # Sort by offset
    results.sort(key=lambda x: x['offset_meters'])
    return results


def get_route_data(rutenummer):
    """Get complete route data including geometry, metadata, and matrikkelenhet vector."""
    conn = get_db_connection()

    try:
        # Get route segments
        segments = get_route_segments(conn, rutenummer)
        if not segments:
            return None

        # Combine geometry
        route_geom = combine_route_geometry(conn, segments)
        if not route_geom:
            return None

        # Get route length
        total_length = get_route_length(conn, route_geom)
        total_length_km = total_length / 1000.0

        # Convert geometry to GeoJSON
        geometry_geojson = geometry_to_geojson(conn, route_geom)

        # Get metadata
        metadata = {
            'rutenummer': segments[0]['rutenummer'],
            'rutenavn': segments[0]['rutenavn'],
            'vedlikeholdsansvarlig': segments[0]['vedlikeholdsansvarlig'],
            'total_length_meters': total_length,
            'total_length_km': total_length_km,
            'segment_count': len(segments)
        }

        # Find matrikkelenhet intersections
        intersections = find_matrikkelenhet_intersections(conn, route_geom)

        # Calculate offsets and create matrikkelenhet vector
        matrikkelenhet_vector = calculate_offsets(conn, route_geom, intersections, total_length)

        return {
            'geometry': geometry_geojson,
            'metadata': metadata,
            'matrikkelenhet_vector': matrikkelenhet_vector
        }

    finally:
        conn.close()

