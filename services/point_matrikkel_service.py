"""Service for finding matrikkelenhet based on a point coordinate."""
import json
from typing import Optional, Dict, Any
from .database import db_connection, get_teig_schema, validate_schema_name, quote_identifier
from .route_service import geometry_to_geojson, format_matrikkelenhet
from .matrikkel_owner_service import fetch_owners_for_matrikkelenheter


class PointMatrikkelError(Exception):
    """Exception raised when point matrikkel lookup fails."""
    pass


def get_matrikkelenhet_for_point(lat: float, lon: float, include_owners: bool = False) -> Optional[Dict[str, Any]]:
    """
    Find matrikkelenhet (teig polygon) that contains the given point.

    Args:
        lat: Latitude in WGS84 (EPSG:4326)
        lon: Longitude in WGS84 (EPSG:4326)
        include_owners: If True, fetch owner information from Matrikkel API

    Returns:
        dict with:
            - matrikkelenhet: Formatted matrikkelenhet string
            - bruksnavn: Property name
            - kommunenummer: Municipality number
            - kommunenavn: Municipality name
            - polygon_geometry: GeoJSON Polygon geometry
            - owners: Owner information (if available)
        None if no teig found at point

    Raises:
        PointMatrikkelError: If query fails or point is invalid
    """
    # Validate coordinates
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise PointMatrikkelError("Latitude and longitude must be numbers")

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise PointMatrikkelError("Invalid coordinate range")

    with db_connection() as conn:
        try:
            # Get teig schema
            teig_schema = get_teig_schema(conn)
            if not validate_schema_name(teig_schema):
                raise PointMatrikkelError(f"Invalid TEIG_SCHEMA: {teig_schema}")

            schema_quoted = quote_identifier(teig_schema)

            # Convert point to PostGIS geometry (WGS84 -> UTM 33N)
            # Query: Find teig that contains the point
            query = f"""
                SELECT
                    t.teigid,
                    t.matrikkelnummertekst,
                    t.kommunenummer,
                    t.kommunenavn,
                    t.arealmerknadtekst,
                    t.lagretberegnetareal,
                    m.bruksnavn,
                    m.gardsnummer,
                    m.bruksnummer,
                    m.festenummer,
                    ST_AsGeoJSON(ST_Transform(t.omrade, 4326))::json as polygon_geometry
                FROM {schema_quoted}.teig t
                LEFT JOIN {schema_quoted}.matrikkelenhet m ON m.teig_fk = t.teigid
                WHERE ST_Contains(
                    t.omrade::geometry,
                    ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 25833)
                )
                ORDER BY t.lagretberegnetareal DESC NULLS LAST
                LIMIT 1;
            """

            with conn.cursor() as cur:
                cur.execute(query, (lon, lat))  # PostGIS uses (lon, lat) order
                result = cur.fetchone()

                if not result:
                    return None

                # Parse result
                teigid = result[0]
                matrikkelnummertekst = result[1]
                kommunenummer = result[2]
                kommunenavn = result[3]
                arealmerknadtekst = result[4]
                lagretberegnetareal = result[5]
                bruksnavn = result[6]
                gardsnummer = result[7]
                bruksnummer = result[8]
                festenummer = result[9]
                polygon_geometry = result[10]

                # Parse polygon geometry (might be string or dict)
                if isinstance(polygon_geometry, str):
                    polygon_geometry = json.loads(polygon_geometry)
                elif polygon_geometry is None:
                    raise PointMatrikkelError("Polygon geometry is NULL")

                # Format matrikkelenhet
                formatted_matrikkel = format_matrikkelenhet(
                    kommunenummer,
                    gardsnummer,
                    bruksnummer,
                    festenummer
                ) or matrikkelnummertekst

                # Build result dict
                result_dict = {
                    'matrikkelenhet': formatted_matrikkel,
                    'matrikkelnummertekst': matrikkelnummertekst,
                    'bruksnavn': bruksnavn,
                    'kommunenummer': kommunenummer,
                    'kommunenavn': kommunenavn,
                    'arealmerknadtekst': arealmerknadtekst,
                    'lagretberegnetareal': lagretberegnetareal,
                    'gardsnummer': gardsnummer,
                    'bruksnummer': bruksnummer,
                    'festenummer': festenummer,
                    'polygon_geometry': polygon_geometry,
                    'teigid': teigid
                }

                # Try to fetch owner information only if requested
                if include_owners:
                    # Create a matrikkelenhet item for owner lookup
                    matrikkelenhet_item = {
                        'matrikkelenhet': formatted_matrikkel,
                        'kommunenummer': kommunenummer,
                        'gardsnummer': gardsnummer,
                        'bruksnummer': bruksnummer,
                        'festenummer': festenummer
                    }

                    owner_results = fetch_owners_for_matrikkelenheter([matrikkelenhet_item])
                    if owner_results:
                        item, owner_info, error = owner_results[0]
                        if owner_info and not error:
                            result_dict['owners'] = owner_info
                        elif error:
                            # Store error but don't fail the request
                            result_dict['owner_error'] = str(error)

                return result_dict

        except Exception as e:
            if isinstance(e, PointMatrikkelError):
                raise
            raise PointMatrikkelError(f"Error finding matrikkelenhet for point: {str(e)}")

