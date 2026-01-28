"""API routes."""
import os
import secrets
import traceback
import json
import re
from typing import Optional, Annotated, Dict
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends, Response, status, Header
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv
from .schemas import (
    ErrorResponse,
    GeometryOwnerRequest,
    GeometryOwnerResponse,
    ExcelReportRequest,
    PlaceSearchResponse,
    PointMatrikkelRequest,
    PointMatrikkelResponse,
    RouteSegmentsResponse,
    RouteSegment,
    RouteInfo,
    CompleteRouteResponse,
    Route,
    RoutesResponse,
    RouteSegmentDetail,
    RouteSegmentsDetailResponse,
    RouteLink,
    RouteLinksResponse,
    RouteValidationResponse,
    SegmentByLokalIdResponse,
    RouteAreasResponse,
    RouteAnchorsResponse,
    AnchorNodeInfo,
    PlacenameCandidatesResponse,
    PlacenameCandidate,
    AnchorNameUpsertRequest,
    AnchorNameUpsertResponse,
    FacilityCandidate,
    SignsReportResponse,
    SignsMissingReport,
    SignsProductionResponse,
)
from services.route_service import (
    search_places,
    get_complete_route,
    get_routes_from_view,
    get_route_segments_from_view,
    get_route_links,
    get_segment_uuid_column,
    get_segment_by_lokalid,
    get_route_anchor_nodes,
    get_anchor_node_coords,
)
from services.route_endpoints import list_placename_candidates, list_ruteinfopunkt_facilities, lookup_name_in_stedsnavn_cached, lookup_named_anchor_within_radius, CLUSTER_RADIUS_METERS
from services.operational_database import op_db_connection
from services.operational_store import upsert_endpoint_name, get_endpoint_names_for_anchors
from services.signs import get_signs_for_route, get_signs_for_prefix, get_signs_for_bbox, build_sign_production_rows
from services.validators import get_validator_registry
from collections import defaultdict
from services.database import db_connection, get_route_schema, get_teig_schema, quote_identifier, ROUTE_SCHEMA
from services.excel_report import generate_owners_excel_from_data
from services.geometry_owner_service import get_owners_for_linestring, GeometryOwnerError
from services.point_matrikkel_service import get_matrikkelenhet_for_point, PointMatrikkelError
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


def get_optional_user(credentials: Optional[HTTPBasicCredentials] = Depends(HTTPBasic(auto_error=False))):
    """
    Optional authentication - returns user if authenticated, None otherwise.
    Does not raise 401 if not authenticated, just returns None.
    """
    if credentials is None:
        return None

    is_user_ok = secrets.compare_digest(credentials.username, SHARED_USERNAME)
    is_pass_ok = secrets.compare_digest(credentials.password, SHARED_PASSWORD)

    if is_user_ok and is_pass_ok:
        return {"username": SHARED_USERNAME}

    return None

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
        # This will raise ValueError if any Matrikkel API errors occur
        excel_bytes = generate_owners_excel_from_data(
            matrikkelenhet_vector,
            request.metadata,
            request.title
        )

        # Create filename with fixed name and date: eierliste_{dato}.xlsx
        date_str = datetime.now().strftime('%Y%m%d')
        filename = f"eierliste_{date_str}.xlsx"

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )
    except HTTPException:
        # Re-raise HTTPException - don't catch these
        raise
    except ValueError as e:
        # This is raised when Matrikkel API errors are detected
        # Return 400 Bad Request with error summary
        print(f"Matrikkel API errors detected, Excel report not generated: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=str(e)
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
    except HTTPException:
        # Re-raise HTTPException - don't catch these
        raise
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


@router.post("/point/matrikkelenhet", response_model=PointMatrikkelResponse, responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_point_matrikkelenhet(
    request: PointMatrikkelRequest,
    user: Optional[Dict] = Depends(get_optional_user)
):
    """
    Get matrikkelenhet (teig polygon) for a point coordinate.

    Accepts a point (latitude, longitude) in WGS84 and returns the teig polygon
    that contains the point, along with matrikkelenhet information.

    Owner information is only included if the user is authenticated.
    Without authentication, only matrikkelenhet metadata is returned.

    Example request:
    ```json
    {
      "lat": 59.9139,
      "lon": 10.7522
    }
    ```

    Returns:
    - matrikkelenhet: Formatted matrikkelenhet string
    - polygon_geometry: GeoJSON Polygon geometry of the teig
    - Additional matrikkelenhet metadata (bruksnavn, kommunenummer, etc.)
    - owners: Owner information (only if authenticated)
    """
    try:
        # Only fetch owner information if user is authenticated
        include_owners = user is not None
        result = get_matrikkelenhet_for_point(request.lat, request.lon, include_owners=include_owners)

        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"No matrikkelenhet found at point ({request.lat}, {request.lon})"
            )

        return PointMatrikkelResponse(**result)
    except HTTPException:
        # Re-raise HTTPException (404, etc.) - don't catch these
        raise
    except PointMatrikkelError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        print(f"Error getting matrikkelenhet for point: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error processing point: {str(e)}"
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
    # Ensure all lists are the same length (pad with None if needed)
    max_len = max(
        len(rutenummer_list) if rutenummer_list else 0,
        len(rutenavn_list) if rutenavn_list else 0,
        len(rutetype_list) if rutetype_list else 0,
        len(vedlikeholdsansvarlig_list) if vedlikeholdsansvarlig_list else 0
    )

    # Pad shorter lists with None
    if rutenavn_list and len(rutenavn_list) < max_len:
        rutenavn_list = list(rutenavn_list) + [None] * (max_len - len(rutenavn_list))
    if rutetype_list and len(rutetype_list) < max_len:
        rutetype_list = list(rutetype_list) + [None] * (max_len - len(rutetype_list))
    if vedlikeholdsansvarlig_list and len(vedlikeholdsansvarlig_list) < max_len:
        vedlikeholdsansvarlig_list = list(vedlikeholdsansvarlig_list) + [None] * (max_len - len(vedlikeholdsansvarlig_list))

    seen_rutenummer = set()
    routes_info = []
    for rutenummer, rutenavn, rutetype, vedlikeholdsansvarlig in zip(
        rutenummer_list, rutenavn_list or [], rutetype_list or [], vedlikeholdsansvarlig_list or []
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
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
    rutenummer_prefix: Annotated[Optional[str], Query(description="Filter by route number prefix (e.g., 'bre')")] = None
) -> JSONResponse:
    """
    Get links filtered by bounding box and optionally by route number prefix.

    Returns GeoJSON FeatureCollection with link geometries and properties.

    Example:
    - /api/v1/links?bbox=10.0,59.0,11.0,60.0&limit=100
    - /api/v1/links?bbox=10.0,59.0,11.0,60.0&rutenummer_prefix=bre
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
            # Find links table/view in stiflyt schema
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

            # Build WHERE clause with optional route prefix filter
            where_conditions = [
                "l.geom && ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), %s)",
                "l.geom IS NOT NULL"
            ]
            params = [xmin, ymin, xmax, ymax, LINKS_SRID]

            # Filter by route number prefix if provided
            if rutenummer_prefix:
                if 'rutenummer_list' in existing_columns:
                    # Filter links where any route number in the list starts with the prefix
                    where_conditions.append(
                        "EXISTS (SELECT 1 FROM unnest(l.rutenummer_list) AS rn WHERE rn LIKE %s)"
                    )
                    params.append(f"{rutenummer_prefix}%")
                else:
                    # If rutenummer_list column doesn't exist, we can't filter
                    # Return empty result set
                    return create_feature_collection_response([])

            where_clause = "WHERE " + " AND ".join(where_conditions)
            params.extend([limit, offset])

            query = f"""
                SELECT
                    {', '.join(select_parts)}
                FROM {full_routes_view_name} l
                {where_clause}
                ORDER BY l.link_id
                LIMIT %s
                OFFSET %s
            """

            # bbox is in WGS84 (4326), transform to LINKS_SRID for spatial index
            cur.execute(query, tuple(params))
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

        # Debug logging for route arrays
        link_id = row.get("link_id")
        if link_id:
            print(f"[DEBUG] Link {link_id}: rutenummer_list={rutenummer_list}, length={len(rutenummer_list)}")
            print(f"[DEBUG] Link {link_id}: rutenavn_list length={len(rutenavn_list) if rutenavn_list else 0}")
            print(f"[DEBUG] Link {link_id}: rutetype_list length={len(rutetype_list) if rutetype_list else 0}")
            print(f"[DEBUG] Link {link_id}: vedlikeholdsansvarlig_list length={len(vedlikeholdsansvarlig_list) if vedlikeholdsansvarlig_list else 0}")

        # Build route information from parallel arrays
        routes_info = build_routes_info_from_arrays(
            rutenummer_list, rutenavn_list, rutetype_list, vedlikeholdsansvarlig_list
        )

        # Debug logging for built routes info
        if link_id:
            print(f"[DEBUG] Link {link_id}: Built {len(routes_info)} route(s): {[r.get('rutenummer') for r in routes_info]}")

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
                # Find anchor_nodes relation (table, view or materialized view) in stiflyt schema.
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
                    print("Anchor nodes relation not found in stiflyt schema")
                    return create_feature_collection_response([])

                anchor_nodes_table_quoted = quote_identifier(table_row["relname"])
                full_anchor_nodes_name = f"{schema_quoted}.{anchor_nodes_table_quoted}"

                # SELECT clause - only node_id and geometry (names come from ops.endpoint_names)
                select_clause = f"""
                    SELECT
                        node_id,
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

        # Get anchor node IDs to fetch names from operational database
        anchor_ids = [row["node_id"] for row in rows if row.get("node_id") is not None]

        # Fetch names from operational database (ops.endpoint_names)
        endpoint_names = {}
        if anchor_ids:
            from services.operational_database import op_db_connection
            from services.operational_store import get_endpoint_names_for_anchors
            try:
                with op_db_connection() as op_conn:
                    endpoint_names = get_endpoint_names_for_anchors(
                        op_conn,
                        anchor_ids,
                        rutenummer=None  # Get global names (not route-specific)
                    )
            except Exception as e:
                print(f"Error fetching endpoint names: {str(e)}")
                # Continue without names if operational DB is unavailable

        # Build GeoJSON FeatureCollection
        features = []
        for row in rows:
            geometry = parse_geometry(row.get("geometry"))
            if not geometry:
                continue  # Skip nodes without geometry

            node_id = row["node_id"]
            properties = {
                "node_id": node_id
            }

            # Add name from operational database if available
            name_info = endpoint_names.get(node_id)
            if name_info:
                properties["navn"] = name_info.get("name")
                properties["navn_kilde"] = name_info.get("source_type")
                properties["navn_distance_m"] = name_info.get("distance_meters")
                if name_info.get("validated_at"):
                    properties["is_validated"] = True

            feature = {
                "type": "Feature",
                "id": node_id,
                "geometry": geometry,
                "properties": properties
            }
            features.append(feature)

        return create_feature_collection_response(features)
    except Exception as e:
        # If table doesn't exist or any other error, return empty FeatureCollection
        print(f"Error loading anchor nodes: {str(e)}")
        return create_feature_collection_response([])


@router.get("/routes/{rutenummer}/anchors", response_model=RouteAnchorsResponse)
async def get_route_anchors(
    rutenummer: str,
):
    """List anchor nodes for a route, with validated names if present."""
    try:
        with db_connection() as conn:
            anchors = get_route_anchor_nodes(conn, rutenummer)

        if not anchors:
            return RouteAnchorsResponse(rutenummer=rutenummer, anchors=[], total=0)

        anchor_ids = [a["anchor_node_id"] for a in anchors]
        overrides = {}
        with op_db_connection() as op_conn:
            overrides = get_endpoint_names_for_anchors(op_conn, anchor_ids, rutenummer=rutenummer)

        anchor_models = []
        for anchor in anchors:
            override = overrides.get(anchor["anchor_node_id"])
            if override and override.get("validated_at"):
                override = {
                    **override,
                    "validated_at": override["validated_at"].isoformat(),
                }
            if not override:
                cluster_name = lookup_named_anchor_within_radius(
                    conn,
                    anchor["lon"],
                    anchor["lat"],
                    radius_meters=CLUSTER_RADIUS_METERS,
                )
                if cluster_name:
                    override = {
                        "name": cluster_name.get("name"),
                        "source_type": cluster_name.get("source"),
                        "source_id": cluster_name.get("source_id"),
                        "distance_meters": cluster_name.get("distance_meters"),
                        "validated_by": None,
                        "validated_at": None,
                    }

            if not override:
                stedsnavn = lookup_name_in_stedsnavn_cached(
                    conn,
                    anchor["lon"],
                    anchor["lat"],
                    search_radius_meters=500.0,
                    anchor_node_id=anchor["anchor_node_id"],
                )
                if stedsnavn:
                    override = {
                        "name": stedsnavn.get("name"),
                        "source_type": stedsnavn.get("source"),
                        "source_id": stedsnavn.get("source_id"),
                        "distance_meters": stedsnavn.get("distance_meters"),
                        "validated_by": None,
                        "validated_at": None,
                    }
            anchor_models.append(
                AnchorNodeInfo(
                    anchor_node_id=anchor["anchor_node_id"],
                    coordinates=[anchor["lon"], anchor["lat"]],
                    link_count=anchor["link_count"],
                    name=override,
                )
            )

        return RouteAnchorsResponse(
            rutenummer=rutenummer,
            anchors=anchor_models,
            total=len(anchor_models),
        )
    except Exception as e:
        print(f"Error loading route anchors: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error loading route anchors: {str(e)}")


@router.get("/anchors/{anchor_id}/placenames", response_model=PlacenameCandidatesResponse)
async def get_anchor_placenames(
    anchor_id: int,
    radius: Annotated[float, Query(ge=10.0, le=5000.0, description="Search radius in meters")] = 500.0,
    limit: Annotated[int, Query(ge=1, le=50, description="Maximum number of candidates")] = 10,
):
    """List nearby placename candidates for an anchor node."""
    with db_connection() as conn:
        coords = get_anchor_node_coords(conn, anchor_id)
        if not coords:
            raise HTTPException(status_code=404, detail=f"Anchor node {anchor_id} not found")
        candidates = list_placename_candidates(
            conn,
            coords["lon"],
            coords["lat"],
            search_radius_meters=radius,
            limit=limit,
        )
        facilities = list_ruteinfopunkt_facilities(
            conn,
            coords["lon"],
            coords["lat"],
            search_radius_meters=radius,
            limit=limit,
        )

    candidate_models = [
        PlacenameCandidate(
            name=c["name"],
            source_type=c["source"],
            source_id=c.get("source_id"),
            distance_meters=c.get("distance_meters"),
            tilrettelegging=c.get("tilrettelegging"),
        )
        for c in candidates
    ]
    facility_models = [
        FacilityCandidate(
            name=f["name"],
            source_id=f.get("source_id"),
            distance_meters=f.get("distance_meters"),
            tilrettelegging=f.get("tilrettelegging"),
        )
        for f in facilities
    ]

    return PlacenameCandidatesResponse(
        anchor_node_id=anchor_id,
        radius_meters=radius,
        candidates=candidate_models,
        facilities=facility_models,
    )


@router.post("/anchors/{anchor_id}/name", response_model=AnchorNameUpsertResponse)
async def upsert_anchor_name(
    anchor_id: int,
    request: AnchorNameUpsertRequest,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Upsert a validated name for an anchor node."""
    validated_by = x_user or "anonymous"
    anchor_coords = None
    with db_connection() as conn:
        anchor_coords = get_anchor_node_coords(conn, anchor_id)
    with op_db_connection() as conn:
        row = upsert_endpoint_name(
            conn,
            anchor_node_id=anchor_id,
            rutenummer=request.rutenummer,
            name=request.name,
            source_type=request.source_type,
            source_id=request.source_id,
            distance_meters=request.distance_meters,
            validated_by=validated_by,
            anchor_lon=anchor_coords.get("lon") if anchor_coords else None,
            anchor_lat=anchor_coords.get("lat") if anchor_coords else None,
        )

    validated_at = row.get("validated_at")
    if validated_at:
        validated_at = validated_at.isoformat()

    return AnchorNameUpsertResponse(
        anchor_node_id=row.get("anchor_node_id", anchor_id),
        rutenummer=row.get("rutenummer"),
        name=row.get("name", request.name),
        source_type=row.get("source_type", request.source_type),
        source_id=row.get("source_id"),
        distance_meters=row.get("distance_meters"),
        validated_by=row.get("validated_by", validated_by),
        validated_at=validated_at,
    )


@router.get("/routes/segments", response_model=RouteSegmentsResponse)
async def get_route_segments(
    rutenummer_prefix: Annotated[Optional[str], Query(description="Filter by route number prefix (e.g., 'bre')")] = None,
    vedlikeholdsansvarlig: Annotated[Optional[str], Query(description="Filter by organization (pattern match, e.g., 'DNT Oslo' or 'DNT')")] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum number of results")] = 100,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
    include_geometry: Annotated[bool, Query(description="Include GeoJSON geometry in response")] = False
) -> RouteSegmentsResponse:
    """
    Get route segments filtered by rutenummer prefix and/or vedlikeholdsansvarlig.

    Returns route segments from fotrute and fotruteinfo tables matching the specified filters.

    At least one filter (rutenummer_prefix or vedlikeholdsansvarlig) must be provided.

    Example:
    - /api/v1/routes/segments?rutenummer_prefix=bre&vedlikeholdsansvarlig=DNT Oslo
    - /api/v1/routes/segments?rutenummer_prefix=bre&limit=50&include_geometry=true
    """
    # Validate that at least one filter is provided
    if not rutenummer_prefix and not vedlikeholdsansvarlig:
        raise HTTPException(
            status_code=400,
            detail="At least one filter must be provided: rutenummer_prefix or vedlikeholdsansvarlig"
        )

    try:
        with db_connection() as conn:
            route_schema = get_route_schema(conn)
            schema_quoted = quote_identifier(route_schema)

            # Build WHERE clause dynamically based on filters
            where_conditions = []
            params = []

            if rutenummer_prefix:
                where_conditions.append(f"fi.rutenummer LIKE %s")
                params.append(f"{rutenummer_prefix}%")

            if vedlikeholdsansvarlig:
                where_conditions.append(f"fi.vedlikeholdsansvarlig ILIKE %s")
                params.append(f"%{vedlikeholdsansvarlig}%")

            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""

            # Build SELECT clause
            uuid_col = get_segment_uuid_column(conn, schema=route_schema)
            select_parts = [
                "f.objid",
                "fi.rutenummer",
                "fi.rutenavn",
                "fi.vedlikeholdsansvarlig",
                "ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters"
            ]

            if uuid_col:
                select_parts.append(f"f.{uuid_col}::text as object_uuid")

            if include_geometry:
                select_parts.append("ST_AsGeoJSON(ST_Transform(f.senterlinje::geometry, 4326))::json as geometry")

            # Build query with count for total
            query = f"""
                WITH filtered_segments AS (
                    SELECT
                        {', '.join(select_parts)}
                    FROM {schema_quoted}.fotrute f
                    JOIN {schema_quoted}.fotruteinfo fi ON fi.fotrute_fk = f.objid
                    {where_clause}
                )
                SELECT
                    *,
                    COUNT(*) OVER() as total_count
                FROM filtered_segments
                ORDER BY rutenummer, objid
                LIMIT %s
                OFFSET %s
            """

            params.extend([limit, offset])

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

            # Extract total count from first row (all rows have same value due to window function)
            total_count = rows[0]['total_count'] if rows else 0

            # Group segments by objid and collect routes
            segments_dict = {}
            for row in rows:
                objid = row["objid"]
                if uuid_col and not row.get("object_uuid"):
                    raise ValueError(f"Missing object_uuid for segment objid {objid}")

                # Initialize segment if not seen before
                if objid not in segments_dict:
                    segments_dict[objid] = {
                        "objid": objid,
                        "object_uuid": row.get("object_uuid"),
                        "routes": [],
                        "length_meters": float(row["length_meters"]) if row.get("length_meters") is not None else None,
                        "geometry": None
                    }

                    # Store geometry (same for all rows with same objid)
                    if include_geometry and row.get("geometry"):
                        segments_dict[objid]["geometry"] = parse_geometry(row["geometry"])

                # Add route information to the segment
                route_info = RouteInfo(
                    rutenummer=row["rutenummer"],
                    rutenavn=row.get("rutenavn"),
                    vedlikeholdsansvarlig=row.get("vedlikeholdsansvarlig")
                )

                # Only add if not already present (avoid duplicates by rutenummer)
                existing_rutenummer = {r.rutenummer for r in segments_dict[objid]["routes"]}
                if route_info.rutenummer not in existing_rutenummer:
                    segments_dict[objid]["routes"].append(route_info)

            # Convert to list of RouteSegment objects
            segments = []
            for objid, segment_data in segments_dict.items():
                segment = RouteSegment(
                    objid=segment_data["objid"],
                    object_uuid=segment_data.get("object_uuid"),
                    routes=segment_data["routes"],
                    length_meters=segment_data["length_meters"],
                    geometry=segment_data["geometry"]
                )
                segments.append(segment)

            return RouteSegmentsResponse(
                segments=segments,
                total=total_count,
                limit=limit,
                offset=offset
            )

    except HTTPException:
        # Re-raise HTTPException - don't catch these
        raise
    except Exception as e:
        print(f"Error querying route segments: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error querying route segments: {str(e)}"
        )


@router.get("/routes/{rutenummer}/complete", response_model=CompleteRouteResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_complete_route_endpoint(
    rutenummer: str,
    include_geometry: Annotated[bool, Query(description="Include GeoJSON geometry in response")] = True,
    include_segments: Annotated[bool, Query(description="Include individual segment details")] = False,
    include_endpoint_names: Annotated[bool, Query(description="Lookup and include from/to place names")] = True
) -> CompleteRouteResponse:
    """
    Get a complete route by combining all segments with the same rutenummer.

    This endpoint:
    - Combines all route segments with the same rutenummer into a complete route geometry
    - Finds from/to place names via stedsnavn lookup (ruteinfopunkt first, then stedsnavn)
    - Returns route metadata (rutenavn, vedlikeholdsansvarlig, length, etc.)

    The route geometry is reconstructed by following connections between segments.
    If segments cannot be connected, they are returned as separate components (MultiLineString).

    Example:
    - /api/v1/routes/bre-1/complete
    - /api/v1/routes/bre-1/complete?include_geometry=false&include_segments=true

    Returns:
    - Complete route with combined geometry, endpoint names, and metadata
    - 404 if rutenummer not found
    """
    try:
        with db_connection() as conn:
            route_data = get_complete_route(
                conn,
                rutenummer,
                include_geometry=include_geometry,
                include_segments=include_segments,
                include_endpoint_names=include_endpoint_names
            )

            if route_data is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Route with rutenummer '{rutenummer}' not found"
                )

            return CompleteRouteResponse(**route_data)

    except HTTPException:
        # Re-raise HTTPException (404, etc.) - don't catch these
        raise
    except Exception as e:
        print(f"Error getting complete route: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error processing complete route: {str(e)}"
        )


@router.get("/routes", response_model=RoutesResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_routes(
    prefix: Annotated[Optional[str], Query(description="Filter by route number prefix (e.g., 'bre', 'jot', 'ron')")] = None,
    vedlikeholdsansvarlig: Annotated[Optional[str], Query(description="Filter by organization (pattern match)")] = None,
    bbox: Annotated[Optional[str], Query(description="Bounding box as 'xmin,ymin,xmax,ymax' in WGS84")] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum number of results")] = 100,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
    include_geometry: Annotated[bool, Query(description="Include GeoJSON geometry in response")] = False
) -> RoutesResponse:
    """
    Get routes from stiflyt.routes materialized view.

    Supports filtering by:
    - prefix: Route number prefix (e.g., "bre", "jot", "ron")
    - vedlikeholdsansvarlig: Organization name (pattern match)
    - bbox: Bounding box for spatial filtering

    Example:
    - /api/v1/routes?prefix=bre
    - /api/v1/routes?vedlikeholdsansvarlig=DNT
    - /api/v1/routes?bbox=10.0,59.0,11.0,60.0
    - /api/v1/routes?prefix=bre&include_geometry=true
    """
    try:
        # Parse bbox if provided
        bbox_tuple = None
        if bbox:
            try:
                bbox_tuple = parse_bbox(bbox)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid bbox format: {e}")

        with db_connection() as conn:
            routes, total_count = get_routes_from_view(
                conn,
                prefix=prefix,
                vedlikeholdsansvarlig=vedlikeholdsansvarlig,
                bbox=bbox_tuple,
                limit=limit,
                offset=offset,
                include_geometry=include_geometry
            )

        # Convert to Pydantic models
        route_models = []
        for route in routes:
            route_models.append(Route(**route))

        return RoutesResponse(
            routes=route_models,
            total=total_count,
            limit=limit,
            offset=offset
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error querying routes: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error querying routes: {str(e)}"
        )


@router.get("/routes/areas", response_model=RouteAreasResponse, responses={500: {"model": ErrorResponse}})
async def get_route_areas(
    vedlikeholdsansvarlig: Annotated[Optional[str], Query(description="Filter by organization (loose token match)")] = None,
    debug: Annotated[bool, Query(description="Include debug token match info")] = False,
    debug_prefix: Annotated[Optional[str], Query(description="Debug: list vedlikeholdsansvarlig for rutenummer prefix")] = None
) -> RouteAreasResponse:
    """
    Get unique 3-letter area prefixes from route segments.

    If vedlikeholdsansvarlig is provided, it is matched loosely by tokens
    (all tokens must appear in the string, case-insensitive).
    """
    try:
        with db_connection() as conn:
            route_schema = get_route_schema(conn)
            schema_quoted = quote_identifier(route_schema)

            where_conditions = ["fi.rutenummer IS NOT NULL", "fi.rutenummer <> ''"]
            params = []

            tokens = []
            if vedlikeholdsansvarlig:
                tokens = [t for t in re.split(r'\s+', vedlikeholdsansvarlig.strip()) if t]
                for token in tokens:
                    where_conditions.append("fi.vedlikeholdsansvarlig ILIKE %s")
                    params.append(f"%{token}%")

            where_clause = "WHERE " + " AND ".join(where_conditions)

            query = f"""
                SELECT DISTINCT LOWER(SUBSTRING(fi.rutenummer FROM 1 FOR 3)) as area
                FROM {schema_quoted}.fotruteinfo fi
                {where_clause}
                ORDER BY area
            """

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

            areas = [row.get("area") for row in rows if row.get("area")]

            debug_payload = None
            if vedlikeholdsansvarlig and debug:
                # Debug: show how many rows matched each token
                debug_counts = []
                for token in tokens:
                    debug_query = f"""
                        SELECT COUNT(*) as count
                        FROM {schema_quoted}.fotruteinfo fi
                        WHERE fi.vedlikeholdsansvarlig ILIKE %s
                    """
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(debug_query, (f"%{token}%",))
                        row = cur.fetchone()
                        debug_counts.append({"token": token, "count": row.get("count", 0) if row else 0})
                debug_payload = {
                    "tokens": tokens,
                    "token_counts": debug_counts,
                }

            if debug_prefix:
                prefix = debug_prefix.strip().lower()
                if prefix:
                    prefix_query = f"""
                        SELECT
                            fi.vedlikeholdsansvarlig as value,
                            COUNT(*) as count
                        FROM {schema_quoted}.fotruteinfo fi
                        WHERE fi.rutenummer ILIKE %s
                        GROUP BY fi.vedlikeholdsansvarlig
                        ORDER BY count DESC
                    """
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(prefix_query, (f"{prefix}%",))
                        prefix_rows = cur.fetchall()
                    prefix_entries = []
                    for row in prefix_rows:
                        value = row.get("value")
                        prefix_entries.append({
                            "value": value if value is not None else "(null)",
                            "count": int(row.get("count", 0)),
                        })
                    if debug_payload is None:
                        debug_payload = {}
                    debug_payload["prefix"] = prefix
                    debug_payload["prefix_vedlikeholdsansvarlig"] = prefix_entries

        return RouteAreasResponse(
            areas=areas,
            total=len(areas),
            vedlikeholdsansvarlig=vedlikeholdsansvarlig,
            debug=debug_payload
        )
    except Exception as e:
        print(f"Error querying route areas: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error querying route areas: {str(e)}"
        )



@router.get("/routes/bulk", response_model=RoutesResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_routes_bulk(
    rutenummer: Annotated[str, Query(description="Comma-separated list of route numbers (e.g., 'bre10,bre11,jot5')")],
    include_geometry: Annotated[bool, Query(description="Include GeoJSON geometry in response")] = False
) -> RoutesResponse:
    """
    Get multiple routes by their route numbers in a single request (bulk fetch).

    This is more efficient than making individual requests for each route.

    Example:
    - /api/v1/routes/bulk?rutenummer=bre10,bre11,jot5
    - /api/v1/routes/bulk?rutenummer=bre10,bre11&include_geometry=true
    """
    try:
        # Parse comma-separated route numbers
        rutenummer_list = [rn.strip() for rn in rutenummer.split(',') if rn.strip()]

        if not rutenummer_list:
            raise HTTPException(
                status_code=400,
                detail="At least one route number must be provided"
            )

        if len(rutenummer_list) > 100:
            raise HTTPException(
                status_code=400,
                detail="Maximum 100 route numbers allowed per request"
            )

        with db_connection() as conn:
            route_schema = get_route_schema(conn)
            schema_quoted = quote_identifier(route_schema)

            # Build query with IN clause for multiple route numbers
            placeholders = ','.join(['%s'] * len(rutenummer_list))

            select_parts = [
                "rutenummer",
                "rutenavn",
                "vedlikeholdsansvarlig",
                "rutetype",
                "total_length_m",
                "segment_count",
                "segment_objids"
            ]

            if include_geometry:
                select_parts.append("ST_AsGeoJSON(ST_Transform(route_geometry, 4326))::json as route_geometry")

            query = f"""
                SELECT
                    {', '.join(select_parts)}
                FROM {schema_quoted}.routes
                WHERE rutenummer IN ({placeholders})
                ORDER BY rutenummer
            """

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, rutenummer_list)
                rows = cur.fetchall()

            # Build results
            routes = []
            for row in rows:
                route = {
                    'rutenummer': row['rutenummer'],
                    'rutenavn': row.get('rutenavn'),
                    'vedlikeholdsansvarlig': row.get('vedlikeholdsansvarlig'),
                    'rutetype': row.get('rutetype'),
                    'total_length_m': float(row['total_length_m']) if row.get('total_length_m') is not None else 0.0,
                    'segment_count': int(row['segment_count']) if row.get('segment_count') is not None else 0,
                    'segment_objids': row.get('segment_objids')
                }

                if include_geometry and row.get('route_geometry'):
                    route['route_geometry'] = parse_geometry(row['route_geometry'])

                routes.append(route)

            # Get endpoint names for routes (similar to get_routes_from_view)
            if routes:
                rutenummer_list_for_endpoints = [r['rutenummer'] for r in routes]
                endpoint_placeholders = ','.join(['%s'] * len(rutenummer_list_for_endpoints))

                # Check if navn column exists
                has_navn_column = False
                try:
                    with conn.cursor() as check_cur:
                        check_cur.execute("""
                            SELECT EXISTS (
                                SELECT 1
                                FROM information_schema.columns
                                WHERE table_schema = %s
                                  AND table_name = 'anchor_nodes'
                                  AND column_name = 'navn'
                            )
                        """, (route_schema,))
                        has_navn_column = check_cur.fetchone()[0]
                except Exception:
                    has_navn_column = False

                navn_select = "an_a.navn as from_name, an_b.navn as to_name" if has_navn_column else "NULL as from_name, NULL as to_name"

                endpoint_query = f"""
                    WITH route_links_expanded AS (
                        SELECT
                            UNNEST(lwr.rutenummer_list) as rutenummer,
                            lwr.link_id,
                            lwr.a_node,
                            lwr.b_node
                        FROM {schema_quoted}.links_with_routes lwr
                        WHERE lwr.rutenummer_list && ARRAY[{endpoint_placeholders}]
                    ),
                    first_last_nodes AS (
                        SELECT
                            rutenummer,
                            (SELECT a_node FROM route_links_expanded rle2
                             WHERE rle2.rutenummer = rle.rutenummer
                             ORDER BY link_id ASC LIMIT 1) as first_a_node,
                            (SELECT b_node FROM route_links_expanded rle3
                             WHERE rle3.rutenummer = rle.rutenummer
                             ORDER BY link_id DESC LIMIT 1) as last_b_node
                        FROM route_links_expanded rle
                        GROUP BY rutenummer
                    )
                    SELECT
                        fln.rutenummer,
                        {navn_select}
                    FROM first_last_nodes fln
                    LEFT JOIN {schema_quoted}.anchor_nodes an_a ON an_a.anchor_node_id = fln.first_a_node
                    LEFT JOIN {schema_quoted}.anchor_nodes an_b ON an_b.anchor_node_id = fln.last_b_node
                """

                try:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(endpoint_query, rutenummer_list_for_endpoints)
                        endpoint_rows = cur.fetchall()

                    # Map endpoint names to routes
                    endpoint_map = {row['rutenummer']: row for row in endpoint_rows}
                    for route in routes:
                        endpoint_info = endpoint_map.get(route['rutenummer'])
                        if endpoint_info:
                            route['from_name'] = endpoint_info.get('from_name')
                            route['to_name'] = endpoint_info.get('to_name')
                except Exception:
                    # Endpoint lookup is optional, continue without it
                    pass

            # Convert to Pydantic models
            route_models = []
            for route in routes:
                route_models.append(Route(**route))

            return RoutesResponse(
                routes=route_models,
                total=len(route_models),
                limit=len(route_models),
                offset=0
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error querying routes bulk: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error querying routes bulk: {str(e)}"
        )


@router.get("/routes/{rutenummer}", response_model=Route, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_route_by_number(
    rutenummer: str,
    include_geometry: Annotated[bool, Query(description="Include GeoJSON geometry in response")] = False
) -> Route:
    """
    Get a single route by rutenummer from stiflyt.routes materialized view.
    Endpoint names are enriched with dynamic lookup if not in the view.

    Example:
    - /api/v1/routes/bre10
    - /api/v1/routes/bre10?include_geometry=true
    """
    try:
        with db_connection() as conn:
            routes, total_count = get_routes_from_view(
                conn,
                rutenummer=rutenummer,
                limit=1,
                offset=0,
                include_geometry=include_geometry
            )

            if not routes:
                raise HTTPException(
                    status_code=404,
                    detail=f"Route with rutenummer '{rutenummer}' not found"
                )

            route_data = routes[0]

            # Enrich with dynamic endpoint names if missing (use separate connection to avoid transaction issues)
            try:
                from services.route_endpoints import lookup_endpoint_name
                from_name = route_data.get("from_name")
                to_name = route_data.get("to_name")
                needs_from = not from_name or (from_name and from_name.strip() == "")
                needs_to = not to_name or (to_name and to_name.strip() == "")
                if needs_from or needs_to:
                    # Use a fresh connection for enrichment to avoid transaction state issues
                    with db_connection() as enrich_conn:
                        # Get endpoint anchor nodes from links_with_routes
                        anchor_ids = {}
                        try:
                            # Check if table exists first
                            with enrich_conn.cursor() as check_cur:
                                check_cur.execute("""
                                    SELECT EXISTS (
                                        SELECT FROM information_schema.tables
                                        WHERE table_schema = %s AND table_name = 'links_with_routes'
                                    )
                                """, (ROUTE_SCHEMA,))
                                table_exists = check_cur.fetchone()[0]

                            if table_exists:
                                anchor_query = f"""
                                    SELECT
                                        (SELECT a_node FROM {ROUTE_SCHEMA}.links_with_routes
                                         WHERE %s = ANY(rutenummer_list)
                                         ORDER BY link_id ASC LIMIT 1) as first_a_node,
                                        (SELECT b_node FROM {ROUTE_SCHEMA}.links_with_routes
                                         WHERE %s = ANY(rutenummer_list)
                                         ORDER BY link_id DESC LIMIT 1) as last_b_node
                                """
                                with enrich_conn.cursor(row_factory=dict_row) as cur:
                                    cur.execute(anchor_query, (rutenummer, rutenummer))
                                    anchor_row = cur.fetchone()
                                if anchor_row:
                                    if anchor_row.get("first_a_node") is not None:
                                        anchor_ids["from"] = int(anchor_row["first_a_node"])
                                    if anchor_row.get("last_b_node") is not None:
                                        anchor_ids["to"] = int(anchor_row["last_b_node"])
                        except Exception as e:
                            # If query fails, skip enrichment but continue
                            print(f"Warning: Could not get anchor nodes for route {rutenummer}: {e}")
                            anchor_ids = {}

                        # Try validated names first
                        overrides = {}
                        if anchor_ids:
                            try:
                                with op_db_connection() as op_conn:
                                    overrides = get_endpoint_names_for_anchors(
                                        op_conn,
                                        list(anchor_ids.values()),
                                        rutenummer=rutenummer,
                                    )
                            except Exception as e:
                                print(f"Warning: Could not get validated names for route {rutenummer}: {e}")

                        # Fill from name
                        if needs_from:
                            if anchor_ids.get("from"):
                                override = overrides.get(anchor_ids["from"])
                                if override and override.get("name"):
                                    route_data["from_name"] = override.get("name")
                                else:
                                    # Fallback to dynamic lookup
                                    try:
                                        coords = get_anchor_node_coords(enrich_conn, anchor_ids["from"])
                                        if coords:
                                            name_info = lookup_endpoint_name(enrich_conn, coords["lon"], coords["lat"], rutenummer)
                                            if name_info and name_info.get('name'):
                                                route_data["from_name"] = name_info.get('name')
                                    except Exception as e:
                                        print(f"Warning: Could not lookup from name for route {rutenummer}: {e}")
                            else:
                                # No anchor ID found, try geometry-based lookup
                                try:
                                    route_geometry = route_data.get("route_geometry")
                                    if route_geometry:
                                        from services.route_endpoints import extract_route_endpoints
                                        start_point, _ = extract_route_endpoints(route_geometry)
                                        if start_point:
                                            name_info = lookup_endpoint_name(enrich_conn, start_point[0], start_point[1], rutenummer)
                                            if name_info and name_info.get('name'):
                                                route_data["from_name"] = name_info.get('name')
                                except Exception as e:
                                    print(f"Warning: Could not lookup from name via geometry for route {rutenummer}: {e}")

                        # Fill to name
                        if needs_to:
                            if anchor_ids.get("to"):
                                override = overrides.get(anchor_ids["to"])
                                if override and override.get("name"):
                                    route_data["to_name"] = override.get("name")
                                else:
                                    # Fallback to dynamic lookup
                                    try:
                                        coords = get_anchor_node_coords(enrich_conn, anchor_ids["to"])
                                        if coords:
                                            name_info = lookup_endpoint_name(enrich_conn, coords["lon"], coords["lat"], rutenummer)
                                            if name_info and name_info.get('name'):
                                                route_data["to_name"] = name_info.get('name')
                                    except Exception as e:
                                        print(f"Warning: Could not lookup to name for route {rutenummer}: {e}")
                            else:
                                # No anchor ID found, try geometry-based lookup
                                try:
                                    route_geometry = route_data.get("route_geometry")
                                    if route_geometry:
                                        from services.route_endpoints import extract_route_endpoints
                                        _, end_point = extract_route_endpoints(route_geometry)
                                        if end_point:
                                            name_info = lookup_endpoint_name(enrich_conn, end_point[0], end_point[1], rutenummer)
                                            if name_info and name_info.get('name'):
                                                route_data["to_name"] = name_info.get('name')
                                except Exception as e:
                                    print(f"Warning: Could not lookup to name via geometry for route {rutenummer}: {e}")
            except Exception as e:
                # If enrichment fails entirely, log but continue with route data from view
                print(f"Warning: Could not enrich endpoint names for route {rutenummer}: {e}")

            return Route(**route_data)

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting route: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error getting route: {str(e)}"
        )


@router.get("/routes/{rutenummer}/segments", response_model=RouteSegmentsDetailResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_route_segments_detail(
    rutenummer: str,
    include_geometry: Annotated[bool, Query(description="Include GeoJSON geometry in response")] = False
) -> RouteSegmentsDetailResponse:
    """
    Get route segments for a specific route from stiflyt.route_segments view.

    Example:
    - /api/v1/routes/bre10/segments
    - /api/v1/routes/bre10/segments?include_geometry=true
    """
    try:
        # Check route exists first
        with db_connection() as check_conn:
            routes, _ = get_routes_from_view(check_conn, rutenummer=rutenummer, limit=1, offset=0)
            if not routes:
                raise HTTPException(
                    status_code=404,
                    detail=f"Route with rutenummer '{rutenummer}' not found"
                )

        # Use separate connection for segments lookup to avoid transaction issues
        with db_connection() as conn:
            segments = get_route_segments_from_view(conn, rutenummer, include_geometry=include_geometry)

        # Convert to Pydantic models
        segment_models = []
        for segment in segments:
            segment_models.append(RouteSegmentDetail(**segment))

        return RouteSegmentsDetailResponse(
            rutenummer=rutenummer,
            segments=segment_models,
            total=len(segment_models)
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting route segments: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error getting route segments: {str(e)}"
        )


@router.get("/routes/{rutenummer}/links", response_model=RouteLinksResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_route_links_endpoint(
    rutenummer: str,
    include_geometry: Annotated[bool, Query(description="Include GeoJSON geometry in response")] = False
) -> RouteLinksResponse:
    """
    Get routing links for a specific route from stiflyt.links table.

    Links represent routing topology (segments between junctions) and may combine
    multiple segments. Useful for navigation/routing purposes.

    Example:
    - /api/v1/routes/bre10/links
    - /api/v1/routes/bre10/links?include_geometry=true
    """
    try:
        # First verify route exists (use separate connection to avoid transaction issues)
        with db_connection() as check_conn:
            routes, _ = get_routes_from_view(check_conn, rutenummer=rutenummer, limit=1, offset=0)
            if not routes:
                raise HTTPException(
                    status_code=404,
                    detail=f"Route with rutenummer '{rutenummer}' not found"
                )

        # Use a fresh connection for getting links
        with db_connection() as conn:
            links = get_route_links(conn, rutenummer, include_geometry=include_geometry)

        # Convert to Pydantic models
        link_models = []
        for link in links:
            link_models.append(RouteLink(**link))

        return RouteLinksResponse(
            rutenummer=rutenummer,
            links=link_models,
            total=len(link_models)
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting route links: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error getting route links: {str(e)}"
        )


@router.get("/routes/{rutenummer}/signs", response_model=SignsReportResponse)
async def get_route_signs_endpoint(
    rutenummer: str,
) -> SignsReportResponse:
    """Get computed signs report for a route."""
    try:
        # Check route exists first
        with db_connection() as check_conn:
            routes, _ = get_routes_from_view(check_conn, rutenummer=rutenummer, limit=1, offset=0)
            if not routes:
                raise HTTPException(
                    status_code=404,
                    detail=f"Route with rutenummer '{rutenummer}' not found"
                )

        # Use separate connection for signs lookup to avoid transaction issues
        with db_connection() as conn:
            report = get_signs_for_route(conn, rutenummer)
        return SignsReportResponse(**report)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting signs for route: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting signs for route: {str(e)}")


@router.get("/signs", response_model=SignsReportResponse)
async def get_signs_by_prefix(
    prefix: Annotated[Optional[str], Query(description="Route prefix (e.g., bre)")] = None,
    bbox: Annotated[Optional[str], Query(description="Bounding box as 'xmin,ymin,xmax,ymax' in WGS84")] = None,
) -> SignsReportResponse:
    """
    Get computed signs report for an area prefix or bounding box.

    Either prefix or bbox must be provided.
    """
    try:
        if not prefix and not bbox:
            raise HTTPException(
                status_code=400,
                detail="Either 'prefix' or 'bbox' parameter must be provided"
            )

        with db_connection() as conn:
            if bbox:
                # Parse bbox
                try:
                    bbox_tuple = parse_bbox(bbox)
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=f"Invalid bbox format: {e}")

                report = get_signs_for_bbox(conn, bbox_tuple)
            else:
                report = get_signs_for_prefix(conn, prefix)
        return SignsReportResponse(**report)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting signs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting signs: {str(e)}")


@router.get("/signs/missing", response_model=SignsMissingReport)
async def get_signs_missing(
    prefix: Annotated[str, Query(min_length=1, description="Route prefix (e.g., bre)")]
) -> SignsMissingReport:
    """Get missing signs report for an area prefix."""
    try:
        with db_connection() as conn:
            report = get_signs_for_prefix(conn, prefix)
        return SignsMissingReport(**report.get("missing", {}))
    except Exception as e:
        print(f"Error getting missing signs for prefix: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting missing signs for prefix: {str(e)}")


@router.get("/signs/production", response_model=SignsProductionResponse)
async def get_signs_production(
    prefix: Annotated[str, Query(min_length=1, description="Route prefix (e.g., bre)")]
) -> SignsProductionResponse:
    """Get production-ready signs rows for an area prefix."""
    try:
        with db_connection() as conn:
            report = get_signs_for_prefix(conn, prefix)
            rows = build_sign_production_rows(report)
        return SignsProductionResponse(scope=report.get("scope", {}), rows=rows)
    except Exception as e:
        print(f"Error getting signs production rows: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting signs production rows: {str(e)}")


@router.get("/routes/{rutenummer}/signs/production", response_model=SignsProductionResponse)
async def get_route_signs_production(
    rutenummer: str,
) -> SignsProductionResponse:
    """Get production-ready signs rows for a route."""
    try:
        # Check route exists first
        with db_connection() as check_conn:
            routes, _ = get_routes_from_view(check_conn, rutenummer=rutenummer, limit=1, offset=0)
            if not routes:
                raise HTTPException(
                    status_code=404,
                    detail=f"Route with rutenummer '{rutenummer}' not found"
                )

        # Use separate connection for signs lookup to avoid transaction issues
        with db_connection() as conn:
            report = get_signs_for_route(conn, rutenummer)
            rows = build_sign_production_rows(report)
        return SignsProductionResponse(scope=report.get("scope", {}), rows=rows)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting route signs production rows: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting route signs production rows: {str(e)}")


@router.get("/routes/{rutenummer}/validate", response_model=RouteValidationResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def validate_route(
    rutenummer: str
) -> RouteValidationResponse:
    """
    Validate a route for metadata consistency and geometry errors.

    This endpoint runs all registered validators on the specified route and returns
    a comprehensive validation report including:
    - Metadata consistency checks (rutenavn, vedlikeholdsansvarlig, rutetype, gradering)
    - Duplicate detection within segments
    - Missing field detection
    - Geometry validation (validity, simplicity, length)
    - Link connectivity checks

    Example:
    - /api/v1/routes/bre10/validate

    Returns:
    - Validation report with errors, warnings, and info messages
    - 404 if rutenummer not found
    """
    try:
        # First verify route exists (use separate connection to avoid transaction issues)
        with db_connection() as check_conn:
            routes, _ = get_routes_from_view(check_conn, rutenummer=rutenummer, limit=1, offset=0)
            if not routes:
                raise HTTPException(
                    status_code=404,
                    detail=f"Route with rutenummer '{rutenummer}' not found"
                )

        # Use a fresh connection for the actual validation
        with db_connection() as conn:
            schema_quoted = quote_identifier(ROUTE_SCHEMA)

            # Get all segments for the route with all metadata including length
            query = f"""
                SELECT
                    f.objid as segment_objid,
                    f.lokalid as segment_lokalid,
                    fi.rutenummer,
                    fi.rutenavn,
                    fi.vedlikeholdsansvarlig,
                    fi.rutetype,
                    fi.gradering,
                    fi.objid as fotruteinfo_objid,
                    ST_Length(ST_Transform(f.senterlinje::geometry, 4326)::geography) as length_meters
                FROM {schema_quoted}.fotrute f
                JOIN {schema_quoted}.fotruteinfo fi ON fi.fotrute_fk = f.objid
                WHERE fi.rutenummer = %s
                ORDER BY f.objid, fi.objid
            """

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, (rutenummer,))
                all_rows = cur.fetchall()

            if not all_rows:
                raise HTTPException(
                    status_code=404,
                    detail=f"No segments found for route '{rutenummer}'"
                )

            # Group by segment_objid to handle multiple fotruteinfo rows per segment
            segments_dict = defaultdict(list)
            for row in all_rows:
                segments_dict[row['segment_objid']].append(row)

            # Prepare segment metadata dump for output
            segment_metadata_dump = []
            for segment_objid, fotruteinfo_rows in sorted(segments_dict.items()):
                segment_length = fotruteinfo_rows[0].get('length_meters') if fotruteinfo_rows else None
                segment_lokalid = fotruteinfo_rows[0].get('segment_lokalid') if fotruteinfo_rows else None
                segment_metadata_dump.append({
                    'segment_objid': str(segment_objid),
                    'segment_lokalid': segment_lokalid,
                    'length_meters': float(segment_length) if segment_length is not None else None,
                    'fotruteinfo_count': len(fotruteinfo_rows),
                    'fotruteinfo_rows': [
                        {
                            'fotruteinfo_objid': row['fotruteinfo_objid'],
                            'rutenummer': row['rutenummer'],
                            'rutenavn': row.get('rutenavn'),
                            'vedlikeholdsansvarlig': row.get('vedlikeholdsansvarlig'),
                            'rutetype': row.get('rutetype'),
                            'gradering': row.get('gradering'),
                        }
                        for row in fotruteinfo_rows
                    ]
                })

            # Prepare route data for validators
            route_data = {
                'rutenummer': rutenummer,
                'segments_dict': segments_dict,
                'all_rows': all_rows,
            }

            # Run validators
            registry = get_validator_registry()
            validation_result = registry.run_validators(route_data, conn)

            # Get link count for summary
            link_count = validation_result.metadata.get('link_count', 0)
            if link_count == 0:
                # Fallback: query directly using a separate connection to avoid transaction issues
                # (validators may have aborted the transaction)
                link_count_query = f"""
                    SELECT COUNT(DISTINCT lwr.link_id) as link_count
                    FROM {schema_quoted}.links_with_routes lwr
                    WHERE %s = ANY(lwr.rutenummer_list)
                """
                with db_connection() as fallback_conn:
                    with fallback_conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(link_count_query, (rutenummer,))
                        link_count_row = cur.fetchone()
                        link_count = link_count_row.get('link_count', 0) if link_count_row else 0

            # Extract summary values
            all_rutenavn = []
            all_vedlikeholdsansvarlig = []
            all_rutetype = []
            all_gradering = []

            for segment_objid, fotruteinfo_rows in segments_dict.items():
                for row in fotruteinfo_rows:
                    if row.get('rutenavn'):
                        all_rutenavn.append(row.get('rutenavn'))
                    if row.get('vedlikeholdsansvarlig'):
                        all_vedlikeholdsansvarlig.append(row.get('vedlikeholdsansvarlig'))
                    if row.get('rutetype'):
                        all_rutetype.append(row.get('rutetype'))
                    if row.get('gradering'):
                        all_gradering.append(row.get('gradering'))

            # Convert ValidationResult to API response format
            errors = []
            warnings = []
            geometry_info = []

            for issue in validation_result.errors:
                errors.append({
                    'type': issue.type,
                    'message': issue.message,
                    'severity': issue.severity.value,
                    'affected_segments': issue.affected_segments,
                    'affected_links': issue.affected_links,
                    'metadata': issue.metadata
                })

            for issue in validation_result.warnings:
                warnings.append({
                    'type': issue.type,
                    'message': issue.message,
                    'severity': issue.severity.value,
                    'affected_segments': issue.affected_segments,
                    'affected_links': issue.affected_links,
                    'metadata': issue.metadata
                })

            for issue in validation_result.info:
                geometry_info.append({
                    'type': issue.type,
                    'message': issue.message,
                    'severity': issue.severity.value,
                    'affected_segments': issue.affected_segments,
                    'affected_links': issue.affected_links,
                    'metadata': issue.metadata
                })

            # Count geometry errors/warnings
            geometry_error_count = len([e for e in errors if 'geometry' in e.get('type', '').lower() or 'link' in e.get('type', '').lower()])
            geometry_warning_count = len([w for w in warnings if 'geometry' in w.get('type', '').lower() or 'link' in w.get('type', '').lower()])

            # Build response
            return RouteValidationResponse(
                rutenummer=rutenummer,
                segment_count=len(segments_dict),
                link_count=link_count,
                status=validation_result.get_status(),
                errors=errors,
                warnings=warnings,
                geometry_info=geometry_info,
                segment_metadata=segment_metadata_dump,
                summary={
                    'total_segments': len(segments_dict),
                    'total_fotruteinfo_rows': len(all_rows),
                    'total_links': link_count,
                    'error_count': len(errors),
                    'warning_count': len(warnings),
                    'geometry_error_count': geometry_error_count,
                    'geometry_warning_count': geometry_warning_count,
                    'rutenavn_values': sorted(set(all_rutenavn)) if all_rutenavn else None,
                    'vedlikeholdsansvarlig_values': sorted(set(all_vedlikeholdsansvarlig)) if all_vedlikeholdsansvarlig else None,
                    'rutetype_values': sorted(set(all_rutetype)) if all_rutetype else None,
                    'gradering_values': sorted(set(all_gradering)) if all_gradering else None,
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error validating route: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error validating route: {str(e)}"
        )


@router.get("/segments/{segment_objid}/routes", responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_segment_routes(
    segment_objid: int
):
    """
    Get all rutenummer (route numbers) that use a specific segment.

    This endpoint returns all routes that share the same segment, which is useful
    for understanding if a segment is used by multiple routes or only one.

    Example:
    - /api/v1/segments/12345/routes

    Returns:
    - List of route information (rutenummer, rutenavn, vedlikeholdsansvarlig) for all routes using this segment
    - 404 if segment not found
    """
    try:
        with db_connection() as conn:
            schema_quoted = quote_identifier(ROUTE_SCHEMA)

            # First verify segment exists
            segment_check_query = f"""
                SELECT objid
                FROM {schema_quoted}.fotrute
                WHERE objid = %s
                LIMIT 1
            """
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(segment_check_query, (segment_objid,))
                segment_exists = cur.fetchone()

            if not segment_exists:
                raise HTTPException(
                    status_code=404,
                    detail=f"Segment with objid '{segment_objid}' not found"
                )

            # Get all routes for this segment
            routes_query = f"""
                SELECT DISTINCT
                    fi.rutenummer,
                    fi.rutenavn,
                    fi.vedlikeholdsansvarlig,
                    fi.rutetype,
                    fi.gradering,
                    fi.objid as fotruteinfo_objid
                FROM {schema_quoted}.fotruteinfo fi
                WHERE fi.fotrute_fk = %s
                ORDER BY fi.rutenummer
            """

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(routes_query, (segment_objid,))
                route_rows = cur.fetchall()

            if not route_rows:
                # Segment exists but has no routes (shouldn't happen, but handle gracefully)
                return {
                    "segment_objid": segment_objid,
                    "routes": [],
                    "total": 0
                }

            routes = []
            for row in route_rows:
                routes.append({
                    "rutenummer": row["rutenummer"],
                    "rutenavn": row.get("rutenavn"),
                    "vedlikeholdsansvarlig": row.get("vedlikeholdsansvarlig"),
                    "rutetype": row.get("rutetype"),
                    "gradering": row.get("gradering"),
                    "fotruteinfo_objid": row["fotruteinfo_objid"]
                })

            return {
                "segment_objid": segment_objid,
                "routes": routes,
                "total": len(routes)
            }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting routes for segment: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error getting routes for segment: {str(e)}"
        )


@router.get("/segments/by-lokalid/{lokalid}", response_model=SegmentByLokalIdResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_segment_by_lokalid_endpoint(
    lokalid: str,
    include_geometry: Annotated[bool, Query(description="Include GeoJSON geometry in response")] = False
) -> SegmentByLokalIdResponse:
    """
    Get a single segment by lokalid with all segment fields and fotruteinfo rows.

    Example:
    - /api/v1/segments/by-lokalid/00661e35-bce5-4106-932f-48f6197dfb58
    - /api/v1/segments/by-lokalid/00661e35-bce5-4106-932f-48f6197dfb58?include_geometry=true
    """
    try:
        with db_connection() as conn:
            result = get_segment_by_lokalid(conn, lokalid, include_geometry=include_geometry)
            if result is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Segment with lokalid '{lokalid}' not found"
                )

            return SegmentByLokalIdResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting segment by lokalid: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error getting segment by lokalid: {str(e)}"
        )