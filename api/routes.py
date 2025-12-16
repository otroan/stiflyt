"""API routes."""
import os
import secrets
import traceback
import json
from typing import Optional, Annotated

from fastapi import APIRouter, HTTPException, Query, Depends, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv
from .schemas import ErrorResponse, GeometryOwnerRequest, GeometryOwnerResponse, ExcelReportRequest, PlaceSearchResponse
from services.route_service import search_places
from services.database import db_connection, get_route_schema, get_teig_schema, quote_identifier, ROUTE_SCHEMA
from services.excel_report import generate_owners_excel_from_data
from services.geometry_owner_service import get_owners_for_linestring, GeometryOwnerError
import psycopg
from psycopg.rows import dict_row

# Load environment variables from .env file (if present)
load_dotenv()

router = APIRouter()
security = HTTPBasic()

# Shared authentication credentials from environment variables
SHARED_USERNAME = os.getenv("SHARED_USERNAME", "dnt")
SHARED_PASSWORD = os.getenv("SHARED_PASSWORD", "dnt")


@router.get("/search/places", response_model=PlaceSearchResponse)
async def search_places_endpoint(
    q: str = Query(..., min_length=2, description="Søkestreng for stedsnavn, rutepunkt eller rute"),
    limit: int = Query(20, ge=1, le=200, description="Maks antall resultater")
):
    """Combined search across ruteinfopunkt, stedsnavn og ruter."""
    results = search_places(q, limit=limit)
    return PlaceSearchResponse(results=results, total=len(results))


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

    # Hvis du vil, kan du returnere en "user"-struktur, men her er det bare fellesbruker
    return {"username": SHARED_USERNAME}

# GET /routes/{rutenummer}/owners.xlsx endpoint removed - replaced by POST /owners.xlsx


@router.post("/owners.xlsx")
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
        matrikkelenhet_vector = [
            item if isinstance(item, dict) else item.dict()
            for item in request.matrikkelenhet_vector
        ]

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


def build_routes_info_from_arrays(rutenummer_list, rutenavn_list, rutetype_list, vedlikeholdsansvarlig_list):
    """
    Build route info objects from parallel arrays, deduplicating by rutenummer.

    Args:
        rutenummer_list: List of route numbers
        rutenavn_list: List of route names
        rutetype_list: List of route types
        vedlikeholdsansvarlig_list: List of organizations

    Returns:
        List of route info dicts, deduplicated by rutenummer
    """
    seen_rutenummer = set()
    routes_info = []
    for rutenummer, rutenavn, rutetype, vedlikeholdsansvarlig in zip(
        rutenummer_list, rutenavn_list, rutetype_list, vedlikeholdsansvarlig_list
    ):
        if rutenummer and rutenummer not in seen_rutenummer:
            seen_rutenummer.add(rutenummer)
            routes_info.append({
                "rutenummer": rutenummer,
                "rutenavn": rutenavn,
                "rutetype": rutetype,
                "vedlikeholdsansvarlig": vedlikeholdsansvarlig
            })
    return routes_info


def create_empty_feature_collection() -> dict:
    """Create an empty GeoJSON FeatureCollection."""
    return {"type": "FeatureCollection", "features": []}


def create_feature_collection_response(features: list) -> JSONResponse:
    """Create a GeoJSON FeatureCollection JSONResponse."""
    return JSONResponse(
        content={"type": "FeatureCollection", "features": features},
        media_type="application/geo+json"
    )


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
                return create_feature_collection_response([])

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
            route_list_columns = [
                'rutenavn_list',
                'rutenummer_list',
                'rutetype_list',
                'vedlikeholdsansvarlig_list'
            ]
            for col in route_list_columns:
                if col in existing_columns:
                    select_parts.append(f"l.{col}")

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

        # Build route information from arrays (parallel arrays from database)
        # Arrays might be None if link has no routes or columns don't exist
        rutenummer_list = row.get("rutenummer_list") or []
        rutenavn_list = row.get("rutenavn_list") or []
        rutetype_list = row.get("rutetype_list") or []
        vedlikeholdsansvarlig_list = row.get("vedlikeholdsansvarlig_list") or []

        # Build route information from parallel arrays
        routes_info = build_routes_info_from_arrays(
            rutenummer_list, rutenavn_list, rutetype_list, vedlikeholdsansvarlig_list
        )

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

    return create_feature_collection_response(features)


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
                    return create_feature_collection_response([])

                anchor_nodes_table_quoted = quote_identifier(table_row["relname"])
                full_anchor_nodes_name = f"{schema_quoted}.{anchor_nodes_table_quoted}"

                # Common SELECT clause (table name is safe - validated via quote_identifier)
                select_clause = f"""
                    SELECT
                        node_id,
                        navn,
                        navn_kilde,
                        navn_distance_m,
                        ST_AsGeoJSON(ST_Transform(geom, 4326))::json as geometry
                    FROM {full_anchor_nodes_name}
                """

                # Build WHERE clause and parameters based on filter type
                if node_ids:
                    node_id_list = [int(nid.strip()) for nid in node_ids.split(',') if nid.strip().isdigit()]
                    if not node_id_list:
                        raise HTTPException(status_code=400, detail="Invalid node_ids format")
                    placeholders = ','.join(['%s'] * len(node_id_list))
                    where_clause = f"WHERE node_id IN ({placeholders})"
                    params = (*node_id_list, limit, offset)
                elif bbox:
                    try:
                        xmin, ymin, xmax, ymax = parse_bbox(bbox)
                    except ValueError as e:
                        raise HTTPException(status_code=400, detail=str(e))
                    where_clause = "WHERE geom && ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), %s) AND geom IS NOT NULL"
                    params = (xmin, ymin, xmax, ymax, LINKS_SRID, limit, offset)
                else:
                    where_clause = ""
                    params = (limit, offset)

                query = f"{select_clause}{where_clause} ORDER BY node_id LIMIT %s OFFSET %s"
                cur.execute(query, params)

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

        return create_feature_collection_response(features)
    except Exception as e:
        # If table doesn't exist or any other error, return empty FeatureCollection
        print(f"Error loading anchor nodes: {str(e)}")
        return create_feature_collection_response([])