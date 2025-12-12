"""
Service for looking up route endpoint names (start and end points).
Looks up names from ruteinfopunkt in turrutebasen first, then falls back to stedsnavn database.
"""
import json
from typing import Optional, Dict, Any, Tuple
from psycopg.rows import dict_row
from .database import ROUTE_SCHEMA, validate_schema_name


def extract_route_endpoints(route_geometry_geojson: Dict[str, Any]) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    """
    Extract start and end point coordinates from a route geometry.

    Args:
        route_geometry_geojson: GeoJSON geometry (LineString or MultiLineString)

    Returns:
        Tuple of (start_point, end_point) where each point is (lon, lat) or None
    """
    if not route_geometry_geojson:
        return None, None

    geom_type = route_geometry_geojson.get('type')
    coordinates = route_geometry_geojson.get('coordinates')

    if not coordinates:
        return None, None

    if geom_type == 'LineString':
        if len(coordinates) < 2:
            return None, None
        start_point = tuple(coordinates[0])  # (lon, lat)
        end_point = tuple(coordinates[-1])  # (lon, lat)
        return start_point, end_point

    elif geom_type == 'MultiLineString':
        if not coordinates or len(coordinates) == 0:
            return None, None

        # Get start from first line, end from last line
        first_line = coordinates[0]
        last_line = coordinates[-1]

        if not first_line or len(first_line) == 0:
            return None, None
        if not last_line or len(last_line) == 0:
            return None, None

        start_point = tuple(first_line[0])  # (lon, lat)
        end_point = tuple(last_line[-1])  # (lon, lat)
        return start_point, end_point

    return None, None


def lookup_name_in_ruteinfopunkt(conn, point_lon: float, point_lat: float, rutenummer: Optional[str] = None, search_radius_meters: float = 100.0) -> Optional[Dict[str, Any]]:
    """
    Look up a name for a point in the ruteinfopunkt table in turrutebasen.

    Args:
        conn: Database connection
        point_lon: Longitude of the point (WGS84)
        point_lat: Latitude of the point (WGS84)
        rutenummer: Optional route number to filter by
        search_radius_meters: Search radius in meters (default: 100m)

    Returns:
        Dict with name, distance, and source, or None if not found
    """
    if not validate_schema_name(ROUTE_SCHEMA):
        return None

    # Check if ruteinfopunkt table exists
    check_table_query = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = %s AND table_name = 'ruteinfopunkt'
        );
    """

    with conn.cursor() as cur:
        cur.execute(check_table_query, (ROUTE_SCHEMA,))
        table_exists = cur.fetchone()[0]

        if not table_exists:
            return None

        # First, check what columns exist in ruteinfopunkt table
        check_columns_query = """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = 'ruteinfopunkt'
            ORDER BY ordinal_position;
        """
        cur.execute(check_columns_query, (ROUTE_SCHEMA,))
        columns = [row[0] for row in cur.fetchall()]

        if not columns:
            return None

        # Find name column (try common patterns)
        name_column = None
        for col in ['navn', 'name', 'stedsnavn', 'punktnavn', 'beskrivelse', 'tekst']:
            if col in columns:
                name_column = col
                break

        # Find geometry column
        geom_column = None
        for col in ['geom', 'geometry', 'posisjon', 'location', 'punkt']:
            if col in columns:
                geom_column = col
                break

        if not name_column or not geom_column:
            # Can't query without name or geometry column
            return None

        # Build query dynamically based on available columns
        # We'll select objid, name column, and distance
        select_cols = ['objid', name_column]
        if 'beskrivelse' in columns and name_column != 'beskrivelse':
            select_cols.append('beskrivelse')

        query = f"""
            SELECT
                {', '.join(select_cols)},
                ST_Distance(
                    ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                    ST_Transform({geom_column}::geometry, 25833)
                ) as distance_meters
            FROM {ROUTE_SCHEMA}.ruteinfopunkt
            WHERE ST_DWithin(
                ST_Transform({geom_column}::geometry, 25833),
                ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                %s
            )
        """

        params = [point_lon, point_lat, point_lon, point_lat, search_radius_meters]

        # Add rutenummer filter if provided (check if there's a relationship column)
        if rutenummer:
            # Check if there's a fotrute_fk or rutenummer column
            if 'fotrute_fk' in columns:
                query += """
                    AND EXISTS (
                        SELECT 1 FROM {schema}.fotruteinfo fi
                        WHERE fi.rutenummer = %s
                        AND fi.fotrute_fk = ruteinfopunkt.fotrute_fk
                    )
                """.format(schema=ROUTE_SCHEMA)
                params.append(rutenummer)
            elif 'rutenummer' in columns:
                query += " AND rutenummer = %s"
                params.append(rutenummer)

        query += " ORDER BY distance_meters ASC LIMIT 1;"

        try:
            cur.execute(query, params)
            result = cur.fetchone()

            if result:
                # Get name from the appropriate column (first non-objid column)
                name = None
                for i in range(1, len(select_cols)):
                    if result[i]:
                        name = result[i]
                        break

                if name:
                    # distance_meters is the last column
                    distance_idx = len(select_cols)
                    return {
                        'name': str(name),
                        'distance_meters': float(result[distance_idx]) if result[distance_idx] else None,
                        'source': 'ruteinfopunkt'
                    }
        except Exception as e:
            # If query fails, log and return None
            print(f"Error querying ruteinfopunkt: {e}")
            return None

    return None


def lookup_name_in_stedsnavn(conn, point_lon: float, point_lat: float, search_radius_meters: float = 500.0) -> Optional[Dict[str, Any]]:
    """
    Look up a name for a point in the stedsnavn database.

    Args:
        conn: Database connection
        point_lon: Longitude of the point (WGS84)
        point_lat: Latitude of the point (WGS84)
        search_radius_meters: Search radius in meters (default: 500m)

    Returns:
        Dict with name, distance, and source, or None if not found
    """
    # First, check if stedsnavn schema/table exists
    # We need to find the schema name - it might be in a config or we need to search for it
    # For now, let's try common schema patterns

    check_schema_query = """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name LIKE '%stedsnavn%' OR schema_name LIKE '%place%name%'
        ORDER BY schema_name
        LIMIT 1;
    """

    with conn.cursor() as cur:
        cur.execute(check_schema_query)
        schema_result = cur.fetchone()

        if not schema_result:
            # Try to find any table with 'stedsnavn' or 'place' in the name
            check_table_query = """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE (table_name LIKE '%stedsnavn%' OR table_name LIKE '%place%name%')
                AND table_type = 'BASE TABLE'
                LIMIT 1;
            """
            cur.execute(check_table_query)
            table_result = cur.fetchone()

            if not table_result:
                return None

            stedsnavn_schema = table_result[0]
            stedsnavn_table = table_result[1]
        else:
            stedsnavn_schema = schema_result[0]
            # Try to find the table name
            check_table_query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                AND table_type = 'BASE TABLE'
                LIMIT 1;
            """
            cur.execute(check_table_query, (stedsnavn_schema,))
            table_result = cur.fetchone()
            if not table_result:
                return None
            stedsnavn_table = table_result[0]

        # Validate schema and table names
        if not validate_schema_name(stedsnavn_schema):
            return None
        if not validate_schema_name(stedsnavn_table):
            return None

        # Look up closest place name within search radius
        # We need to guess the column names - common patterns:
        # - navn, name, stedsnavn
        # - geom, geometry, posisjon, location
        query = f"""
            SELECT
                navn,
                name,
                stedsnavn,
                ST_Distance(
                    ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                    ST_Transform(geom::geometry, 25833)
                ) as distance_meters
            FROM "{stedsnavn_schema}"."{stedsnavn_table}"
            WHERE ST_DWithin(
                ST_Transform(geom::geometry, 25833),
                ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833),
                %s
            )
            AND (navn IS NOT NULL OR name IS NOT NULL OR stedsnavn IS NOT NULL)
            ORDER BY distance_meters ASC
            LIMIT 1;
        """

        try:
            cur.execute(query, [point_lon, point_lat, point_lon, point_lat, search_radius_meters])
            result = cur.fetchone()

            if result:
                # Try to get name from various possible column names
                name = result[0] or result[1] or result[2]  # navn, name, or stedsnavn
                if name:
                    return {
                        'name': name,
                        'distance_meters': float(result[3]) if result[3] else None,
                        'source': 'stedsnavn'
                    }
        except Exception as e:
            # If query fails (wrong column names), return None
            # In production, you might want to log this
            print(f"Error querying stedsnavn: {e}")
            return None

    return None


def lookup_endpoint_name(conn, point_lon: float, point_lat: float, rutenummer: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Look up a name for a route endpoint using hierarchical lookup:
    1. First try ruteinfopunkt (within 100m)
    2. Then try stedsnavn (within 500m)

    Args:
        conn: Database connection
        point_lon: Longitude of the point (WGS84)
        point_lat: Latitude of the point (WGS84)
        rutenummer: Optional route number for filtering ruteinfopunkt

    Returns:
        Dict with name, distance_meters, and source, or None if not found
    """
    # First try ruteinfopunkt (closer search radius)
    result = lookup_name_in_ruteinfopunkt(conn, point_lon, point_lat, rutenummer, search_radius_meters=100.0)
    if result:
        return result

    # Fallback to stedsnavn (larger search radius)
    result = lookup_name_in_stedsnavn(conn, point_lon, point_lat, search_radius_meters=500.0)
    if result:
        return result

    return None


def get_route_endpoint_names(conn, route_geometry_geojson: Dict[str, Any], rutenummer: Optional[str] = None) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Get names for both start and end points of a route.

    Args:
        conn: Database connection
        route_geometry_geojson: GeoJSON geometry of the route
        rutenummer: Optional route number for filtering

    Returns:
        Dict with 'start_point' and 'end_point', each containing name info or None
    """
    start_point, end_point = extract_route_endpoints(route_geometry_geojson)

    result = {
        'start_point': None,
        'end_point': None
    }

    if start_point:
        start_lon, start_lat = start_point
        start_name = lookup_endpoint_name(conn, start_lon, start_lat, rutenummer)
        if start_name:
            result['start_point'] = {
                **start_name,
                'coordinates': [start_lon, start_lat]
            }

    if end_point:
        end_lon, end_lat = end_point
        end_name = lookup_endpoint_name(conn, end_lon, end_lat, rutenummer)
        if end_name:
            result['end_point'] = {
                **end_name,
                'coordinates': [end_lon, end_lat]
            }

    return result

