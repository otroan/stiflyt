"""Service for getting property owners for arbitrary LineString geometry."""
import json
from .database import get_db_connection, db_connection
from .route_service import (
    find_matrikkelenhet_intersections,
    calculate_offsets,
    get_route_length,
    geometry_to_geojson,
    format_matrikkelenhet
)
from .matrikkel_owner_service import fetch_owners_for_matrikkelenheter


class GeometryOwnerError(Exception):
    """Exception raised when geometry owner lookup fails."""
    pass


def get_owners_for_linestring(geometry_geojson):
    """
    Get property owners for a LineString geometry.

    This function works similarly to get_route_data() but accepts
    any LineString geometry instead of looking up route segments.

    Args:
        geometry_geojson: GeoJSON LineString geometry dict

    Returns:
        dict: Geometry owner data with:
            - geometry: Original GeoJSON geometry
            - total_length_meters: Total length of the line
            - total_length_km: Total length in kilometers
            - matrikkelenhet_vector: List of property intersections with owners

    Raises:
        GeometryOwnerError: If geometry is invalid or processing fails
    """
    # Validate geometry type
    if not isinstance(geometry_geojson, dict):
        raise GeometryOwnerError("Geometry must be a GeoJSON object")

    geom_type = geometry_geojson.get('type')
    if geom_type != 'LineString':
        raise GeometryOwnerError(f"Only LineString geometry is supported, got {geom_type}")

    coordinates = geometry_geojson.get('coordinates')
    if not coordinates or not isinstance(coordinates, list) or len(coordinates) < 2:
        raise GeometryOwnerError("LineString must have at least 2 coordinates")

    with db_connection() as conn:
        try:
            # Convert GeoJSON to PostGIS geometry
            # Set SRID to 4326 (WGS84) then transform to 25833 (UTM Zone 33N - Norwegian standard)
            geom_wkt_query = """
                SELECT ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s)::geometry, 4326), 25833) as geom;
            """
            with conn.cursor() as cur:
                cur.execute(geom_wkt_query, (json.dumps(geometry_geojson),))
                result = cur.fetchone()
                if not result or not result[0]:
                    raise GeometryOwnerError("Failed to convert geometry to PostGIS format")
                route_geom = result[0]

            # Get total length
            total_length = get_route_length(conn, route_geom)
            total_length_km = total_length / 1000.0

            if total_length <= 0:
                # LineString has no length - return empty results
                return {
                    'geometry': geometry_geojson,
                    'total_length_meters': 0.0,
                    'total_length_km': 0.0,
                    'matrikkelenhet_vector': []
                }

            # Find matrikkelenhet intersections
            intersections = find_matrikkelenhet_intersections(conn, route_geom)

            if not intersections:
                # No intersections found
                return {
                    'geometry': geometry_geojson,
                    'total_length_meters': total_length,
                    'total_length_km': total_length_km,
                    'matrikkelenhet_vector': []
                }

            # Calculate offsets and create matrikkelenhet vector
            matrikkelenhet_vector = calculate_offsets(conn, route_geom, intersections, total_length)

            # Fetch owner information from Matrikkel API (if credentials are available)
            # This will gracefully handle missing credentials by returning None for owner info
            owner_results = fetch_owners_for_matrikkelenheter(matrikkelenhet_vector)

            # Add owner information to matrikkelenhet_vector
            # Create a mapping from matrikkelenhet identifier to owner info
            owner_info_map = {}
            for item, owner_info, error in owner_results:
                # Use a combination of fields to create a unique key
                key = (
                    item.get('kommunenummer'),
                    item.get('matrikkelenhet'),
                    item.get('offset_meters', 0)
                )
                if owner_info:
                    owner_info_map[key] = owner_info

            # Add owner info to each matrikkelenhet item
            for item in matrikkelenhet_vector:
                key = (
                    item.get('kommunenummer'),
                    item.get('matrikkelenhet'),
                    item.get('offset_meters', 0)
                )
                item['owners'] = owner_info_map.get(key, None)

            return {
                'geometry': geometry_geojson,
                'total_length_meters': total_length,
                'total_length_km': total_length_km,
                'matrikkelenhet_vector': matrikkelenhet_vector
            }

        except Exception as e:
            if isinstance(e, GeometryOwnerError):
                raise
            raise GeometryOwnerError(f"Error processing geometry: {str(e)}")







