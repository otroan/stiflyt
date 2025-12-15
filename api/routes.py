"""API routes."""
import secrets
import traceback
import json
from functools import wraps
from typing import Optional, Callable, Any, Annotated

from fastapi import APIRouter, HTTPException, Query, Path, Depends, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from .schemas import ErrorResponse, GeometryOwnerRequest, GeometryOwnerResponse, ExcelReportRequest, AnchorNodeItem, AnchorNodeResponse, PlaceSearchResponse
from services.route_service import search_places
from services.database import get_db_connection, db_connection, get_route_schema, get_teig_schema, quote_identifier, ROUTE_SCHEMA
from services.excel_report import generate_owners_excel, generate_owners_excel_from_data
from services.geometry_owner_service import get_owners_for_linestring, GeometryOwnerError
import psycopg
from psycopg.rows import dict_row

router = APIRouter()
security = HTTPBasic()


def handle_route_errors(operation_name: str):
    """
    Decorator to handle common error patterns (simplified - no longer route-specific).

    Note: This decorator is kept for compatibility but route-specific error handling
    has been removed since route endpoints are no longer used.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                return result
            except HTTPException:
                raise
            except Exception as e:
                error_detail = str(e)
                print(f"Error {operation_name}: {error_detail}")
                print(traceback.format_exc())
                raise HTTPException(
                    status_code=500,
                    detail=f"Error {operation_name}: {error_detail}"
                )
        return wrapper
    return decorator


# Route-related endpoints removed - routes are not loaded in this part of the tool


@router.get("/search/places", response_model=PlaceSearchResponse)
async def search_places_endpoint(
    q: str = Query(..., min_length=2, description="Søkestreng for stedsnavn, rutepunkt eller rute"),
    limit: int = Query(20, ge=1, le=200, description="Maks antall resultater")
):
    """Combined search across ruteinfopunkt, stedsnavn og ruter."""
    results = search_places(q, limit=limit)
    return PlaceSearchResponse(results=results, total=len(results))


# Route bbox endpoint removed - routes are not loaded in this part of the tool


# Route endpoints removed - routes are not loaded in this part of the tool
# Removed endpoints:
# - GET /routes/{rutenummer}
# - GET /routes/{rutenummer}/segments
# - GET /routes/{rutenummer}/debug
# - GET /routes/{rutenummer}/corrected

def require_shared_login(credentials: HTTPBasicCredentials = Depends(security)):
    """
    Krever at klienten sender riktig basic auth-bruker/passord.
    Bruker constant-time compare for å unngå timing-angrep.
    """

    is_user_ok = secrets.compare_digest(credentials.username, SHARED_USERNAME)
    is_pass_ok = secrets.compare_digest(credentials.password, SHARED_PASSWORD)

    if not (is_user_ok and is_pass_ok):
        # Browser vil typisk vise login-dialog når den får 401 + denne headeren
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Hvis du vil, kan du returnere en “user”-struktur, men her er det bare fellesbruker
    return {"username": SHARED_USERNAME}

SHARED_USERNAME = "dnt"
SHARED_PASSWORD = "dnt"

# GET /routes/{rutenummer}/owners.xlsx endpoint removed - replaced by POST /owners.xlsx


@router.post("/owners.xlsx")
@handle_route_errors("generating owners Excel report")
async def download_owners_excel(
    request: ExcelReportRequest,
    user=Depends(require_shared_login),
):
    """
    Download Excel report with owners information from matrikkelenhet_vector.

    This endpoint can be used for:
    - Drawn lines (send geometry and get matrikkelenhet_vector first)
    - Selected links (send link_ids and get matrikkelenhet_vector first)
    - Any custom geometry

    Requires authentication.
    """
    try:
        # Convert matrikkelenhet_vector items to dict format if needed
        matrikkelenhet_vector = []
        for item in request.matrikkelenhet_vector:
            if isinstance(item, dict):
                matrikkelenhet_vector.append(item)
            else:
                # Convert Pydantic model to dict
                matrikkelenhet_vector.append(item.dict())

        # Generate Excel file
        excel_bytes = generate_owners_excel_from_data(
            matrikkelenhet_vector,
            request.metadata,
            request.title
        )

        # Create filename
        title = request.title or "rapport"
        filename = f"{title}-owners.xlsx"

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )
    except Exception as e:
        print(f"Error generating Excel report: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error generating Excel report: {str(e)}"
        )


@router.post("/geometry/owners", response_model=GeometryOwnerResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_geometry_owners(request: GeometryOwnerRequest):
    """
    Get property owners for a LineString geometry.

    Accepts a GeoJSON LineString geometry and returns all property owners
    along the line, similar to route owner lookup.

    The geometry must be a valid GeoJSON LineString with at least 2 coordinates.
    Coordinates should be in [longitude, latitude] format (WGS84, EPSG:4326).

    Example request:
    ```json
    {
      "geometry": {
        "type": "LineString",
        "coordinates": [[10.0, 59.0], [10.1, 59.1], [10.2, 59.2]]
      }
    }
    ```

    Returns:
    - geometry: Original GeoJSON geometry
    - total_length_meters: Total length of the line in meters
    - total_length_km: Total length in kilometers
    - matrikkelenhet_vector: List of property intersections with owner information
    """
    try:
        result = get_owners_for_linestring(request.geometry)
        return GeometryOwnerResponse(**result)
    except GeometryOwnerError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        print(f"Error getting owners for geometry: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error processing geometry: {str(e)}"
        )


# Default SRID for links table - adjust if your links.geom uses a different SRID
# Common values: 4326 (WGS84), 25833 (UTM 33N), 3857 (Web Mercator)
LINKS_SRID = 25833


def parse_bbox(bbox_str: str) -> tuple[float, float, float, float]:
    """
    Parse bbox string "xmin,ymin,xmax,ymax" into tuple of floats.

    Args:
        bbox_str: Bounding box string in format "xmin,ymin,xmax,ymax"

    Returns:
        Tuple of (xmin, ymin, xmax, ymax) as floats

    Raises:
        ValueError: If bbox string is invalid
    """
    try:
        parts = bbox_str.split(',')
        if len(parts) != 4:
            raise ValueError("bbox must have exactly 4 values")
        xmin, ymin, xmax, ymax = [float(p.strip()) for p in parts]

        if xmin >= xmax:
            raise ValueError("xmin must be less than xmax")
        if ymin >= ymax:
            raise ValueError("ymin must be less than ymax")

        return xmin, ymin, xmax, ymax
    except ValueError as e:
        if "must have exactly" in str(e) or "must be less" in str(e):
            raise
        raise ValueError(f"Invalid bbox format: {e}")


def clamp_limit(limit: int) -> int:
    """Clamp limit to valid range [1, 5000]."""
    return max(1, min(5000, limit))


def parse_geometry(geom_data) -> dict:
    """
    Parse geometry from PostGIS ST_AsGeoJSON result.
    Handles both string and already-parsed dict cases.

    Args:
        geom_data: Geometry data from database (string or dict)

    Returns:
        dict: Parsed geometry as dict
    """
    if isinstance(geom_data, str):
        return json.loads(geom_data)
    elif isinstance(geom_data, dict):
        return geom_data
    else:
        # Fallback: try to convert to dict
        return geom_data


@router.get("/links")
async def get_links(
    bbox: Annotated[str, Query(description="Bounding box as 'xmin,ymin,xmax,ymax'")],
    limit: Annotated[int, Query(ge=1, le=5000, description="Maximum number of results")] = 500,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0
) -> JSONResponse:
    """
    Get links filtered by bounding box.

    Returns GeoJSON FeatureCollection with link geometries and properties.

    Example:
    - /api/v1/links?bbox=10.0,59.0,11.0,60.0&limit=100
    """
    # Parse and validate bbox
    try:
        xmin, ymin, xmax, ymax = parse_bbox(bbox)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Clamp limit
    limit = clamp_limit(limit)

    # Query database
    # Frontend sends bbox in WGS84 (4326), but links.geom is in LINKS_SRID (25833)
    # Transform bbox to match links.geom SRID for efficient spatial index usage
    # Links table is in ROUTE_SCHEMA (same schema as routes)
    with db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Use quoted schema and table name for safety
            route_schema = get_route_schema(conn)
            schema_quoted = quote_identifier(route_schema)
            # Discover links table/view (schema hash changes on import)
            cur.execute(
                """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_name IN ('links_with_routes', 'links')
                    ORDER BY CASE WHEN table_name = 'links_with_routes' THEN 0 ELSE 1 END
                    LIMIT 1
                """,
                (route_schema,),
            )
            table_row = cur.fetchone()
            if not table_row:
                # No links table present; return empty GeoJSON
                return JSONResponse(
                    content={"type": "FeatureCollection", "features": []},
                    media_type="application/geo+json"
                )

            routes_view_quoted = quote_identifier(table_row['table_name'])
            full_routes_view_name = f"{schema_quoted}.{routes_view_quoted}"

            # Check which columns exist in the table
            cur.execute(
                """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                """,
                (route_schema, table_row['table_name']),
            )
            existing_columns = {row['column_name'] for row in cur.fetchall()}

            # Build SELECT clause with only existing columns
            select_parts = [
                "l.link_id",
                "l.a_node",
                "l.b_node",
                "l.length_m",
            ]

            # Add route list columns only if they exist
            has_rutenavn_list = 'rutenavn_list' in existing_columns
            has_rutenummer_list = 'rutenummer_list' in existing_columns
            has_rutetype_list = 'rutetype_list' in existing_columns
            has_vedlikeholdsansvarlig_list = 'vedlikeholdsansvarlig_list' in existing_columns

            if has_rutenavn_list:
                select_parts.append("l.rutenavn_list")
            if has_rutenummer_list:
                select_parts.append("l.rutenummer_list")
            if has_rutetype_list:
                select_parts.append("l.rutetype_list")
            if has_vedlikeholdsansvarlig_list:
                select_parts.append("l.vedlikeholdsansvarlig_list")

            select_parts.append("ST_AsGeoJSON(ST_Transform(l.geom, 4326))::json as geometry")

            query = f"""
                SELECT
                    {', '.join(select_parts)}
                FROM {full_routes_view_name} l
                WHERE l.geom && ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), %s)
                    AND l.geom IS NOT NULL
                ORDER BY l.link_id
                LIMIT %s
                OFFSET %s
            """

            # bbox is in WGS84 (4326), transform to LINKS_SRID for spatial index
            cur.execute(query, (xmin, ymin, xmax, ymax, LINKS_SRID, limit, offset))
            rows = cur.fetchall()

    # Build GeoJSON FeatureCollection
    features = []
    for row in rows:
        # Parse geometry (handles both string and dict from PostGIS)
        geometry = parse_geometry(row["geometry"])

        # Build route information from arrays
        # Arrays might be None if link has no routes or columns don't exist
        rutenavn_list = row.get("rutenavn_list")
        rutenummer_list = row.get("rutenummer_list")
        rutetype_list = row.get("rutetype_list")
        vedlikeholdsansvarlig_list = row.get("vedlikeholdsansvarlig_list")

        # Ensure we have lists (handle None and ensure they're iterable)
        if rutenavn_list is None:
            rutenavn_list = []
        if rutenummer_list is None:
            rutenummer_list = []
        if rutetype_list is None:
            rutetype_list = []
        if vedlikeholdsansvarlig_list is None:
            vedlikeholdsansvarlig_list = []

        # Create list of route info objects (deduplicate by rutenummer)
        routes_info = []
        seen_rutenummer = set()

        # Combine arrays into route info objects
        # Use the longest array as reference, but handle cases where arrays have different lengths
        max_len = max(
            len(rutenavn_list) if rutenavn_list else 0,
            len(rutenummer_list) if rutenummer_list else 0,
            len(rutetype_list) if rutetype_list else 0,
            len(vedlikeholdsansvarlig_list) if vedlikeholdsansvarlig_list else 0
        )

        for i in range(max_len):
            rutenummer = rutenummer_list[i] if rutenummer_list and i < len(rutenummer_list) else None
            rutenavn = rutenavn_list[i] if rutenavn_list and i < len(rutenavn_list) else None
            rutetype = rutetype_list[i] if rutetype_list and i < len(rutetype_list) else None
            vedlikeholdsansvarlig = vedlikeholdsansvarlig_list[i] if vedlikeholdsansvarlig_list and i < len(vedlikeholdsansvarlig_list) else None

            # Only add if we have at least rutenummer and haven't seen it before
            if rutenummer and rutenummer not in seen_rutenummer:
                seen_rutenummer.add(rutenummer)
                routes_info.append({
                    "rutenummer": rutenummer,
                    "rutenavn": rutenavn,
                    "rutetype": rutetype,
                    "vedlikeholdsansvarlig": vedlikeholdsansvarlig
                })

        feature = {
            "type": "Feature",
            "id": row["link_id"],
            "geometry": geometry,
            "properties": {
                "length_m": row["length_m"],
                "a_node": row["a_node"],
                "b_node": row["b_node"],
                "routes": routes_info  # List of route info objects
            }
        }
        features.append(feature)

    feature_collection = {
        "type": "FeatureCollection",
        "features": features
    }

    return JSONResponse(
        content=feature_collection,
        media_type="application/geo+json"
    )


@router.get("/anchor-nodes")
async def get_anchor_nodes(
    node_ids: Annotated[Optional[str], Query(description="Comma-separated list of node IDs")] = None,
    bbox: Annotated[Optional[str], Query(description="Bounding box as 'xmin,ymin,xmax,ymax'")] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum number of results")] = 100,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0
) -> JSONResponse:
    """
    Get anchor nodes with their names and geometry.

    Returns anchor nodes with navn, navn_kilde, navn_distance_m, and geometry.
    Can filter by specific node_ids, bounding box, or return all nodes (up to limit).

    Example:
    - /api/v1/anchor-nodes?node_ids=1,2,3
    - /api/v1/anchor-nodes?bbox=10.0,59.0,11.0,60.0
    - /api/v1/anchor-nodes?limit=100
    """
    try:
        with db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                route_schema = get_route_schema(conn)
                schema_quoted = quote_identifier(route_schema)
                # Discover anchor_nodes relation (table, view or materialized view).
                # We use pg_class/pg_namespace so this works even if anchor_nodes is a MATERIALIZED VIEW.
                cur.execute(
                    """
                        SELECT c.relname AS relname
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = %s
                          AND c.relname = 'anchor_nodes'
                          AND c.relkind IN ('r', 'v', 'm')  -- table, view, materialized view
                        LIMIT 1
                    """,
                    (route_schema,),
                )
                table_row = cur.fetchone()
                if not table_row:
                    print("Anchor nodes relation not found in discovered route schema")
                    feature_collection = {
                        "type": "FeatureCollection",
                        "features": []
                    }
                    return JSONResponse(
                        content=feature_collection,
                        media_type="application/geo+json"
                    )

                anchor_nodes_table_quoted = quote_identifier(table_row["relname"])
                full_anchor_nodes_name = f"{schema_quoted}.{anchor_nodes_table_quoted}"

                if node_ids:
                    # Filter by specific node IDs
                    node_id_list = [int(nid.strip()) for nid in node_ids.split(',') if nid.strip().isdigit()]
                    if not node_id_list:
                        raise HTTPException(status_code=400, detail="Invalid node_ids format")

                    placeholders = ','.join(['%s'] * len(node_id_list))
                    query = f"""
                        SELECT
                            node_id,
                            navn,
                            navn_kilde,
                            navn_distance_m,
                            ST_AsGeoJSON(ST_Transform(geom, 4326))::json as geometry
                        FROM {full_anchor_nodes_name}
                        WHERE node_id IN ({placeholders})
                        ORDER BY node_id
                        LIMIT %s
                        OFFSET %s
                    """
                    cur.execute(query, (*node_id_list, limit, offset))
                elif bbox:
                    # Filter by bounding box
                    try:
                        xmin, ymin, xmax, ymax = parse_bbox(bbox)
                    except ValueError as e:
                        raise HTTPException(status_code=400, detail=str(e))

                    query = f"""
                        SELECT
                            node_id,
                            navn,
                            navn_kilde,
                            navn_distance_m,
                            ST_AsGeoJSON(ST_Transform(geom, 4326))::json as geometry
                        FROM {full_anchor_nodes_name}
                        WHERE geom && ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), %s)
                            AND geom IS NOT NULL
                        ORDER BY node_id
                        LIMIT %s
                        OFFSET %s
                    """
                    cur.execute(query, (xmin, ymin, xmax, ymax, LINKS_SRID, limit, offset))
                else:
                    # Get all nodes (up to limit)
                    query = f"""
                        SELECT
                            node_id,
                            navn,
                            navn_kilde,
                            navn_distance_m,
                            ST_AsGeoJSON(ST_Transform(geom, 4326))::json as geometry
                        FROM {full_anchor_nodes_name}
                        ORDER BY node_id
                        LIMIT %s
                        OFFSET %s
                    """
                    cur.execute(query, (limit, offset))

                rows = cur.fetchall()

        # Build GeoJSON FeatureCollection
        features = []
        for row in rows:
            geometry = parse_geometry(row.get("geometry"))
            if not geometry:
                continue  # Skip nodes without geometry

            feature = {
                "type": "Feature",
                "id": row["node_id"],
                "geometry": geometry,
                "properties": {
                    "node_id": row["node_id"],
                    "navn": row.get("navn"),
                    "navn_kilde": row.get("navn_kilde"),
                    "navn_distance_m": row.get("navn_distance_m")
                }
            }
            features.append(feature)

        feature_collection = {
            "type": "FeatureCollection",
            "features": features
        }

        return JSONResponse(
            content=feature_collection,
            media_type="application/geo+json"
        )
    except Exception as e:
        # If table doesn't exist or any other error, return empty FeatureCollection
        print(f"Error loading anchor nodes: {str(e)}")
        feature_collection = {
            "type": "FeatureCollection",
            "features": []
        }
        return JSONResponse(
            content=feature_collection,
            media_type="application/geo+json"
        )