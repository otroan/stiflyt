"""API routes."""
import os
import secrets
import traceback
import json
import re
import base64
from typing import Optional, Annotated, Dict, List, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends, Response, status, Header, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
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
    RoutesStatisticsResponse,
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
    SignStatusUpsertRequest,
    SignSiteSkiltPatchRequest,
    SignSiteCreateRequest,
    SignSiteDestinationsUpdateRequest,
    SignSiteUpdateRequest,
    SignSiteResponse,
)
from services.route_service import (
    search_places,
    get_complete_route,
    get_routes_from_view,
    get_routes_statistics,
    get_route_segments_from_view,
    get_route_links,
    get_segment_uuid_column,
    get_segment_by_lokalid,
    get_route_anchor_nodes,
    get_anchor_node_coords,
    get_anchor_node_geometry,
)
from services.route_endpoints import list_placename_candidates, list_ruteinfopunkt_facilities, lookup_name_in_stedsnavn_cached, lookup_named_anchor_within_radius, CLUSTER_RADIUS_METERS
from services.operational_database import op_db_connection
from services.operational_store import (
    upsert_endpoint_name,
    get_endpoint_names_for_anchors,
    get_endpoint_names_for_anchor_routes,
    upsert_sign_status,
    update_sign_status_row_by_id,
    create_sign_site,
    get_sign_site_by_id,
    get_sign_site_destinations,
    set_sign_site_destinations,
    add_sign_site_destination,
    remove_sign_site_destination,
    update_sign_site,
    patch_sign_site_skilt,
    accept_sign_candidate,
    reject_sign_candidate,
    allocate_site_code,
    delete_sign_site,
    search_endpoint_names,
    get_distance_correction_factor,
)
from services.signs import (
    get_signs_for_route, get_signs_for_prefix, get_signs_for_bbox, build_sign_production_rows,
    shortest_path_distance, nearest_anchor_node, search_anchor_nodes_by_navn, routable_node_set,
)
from services.sign_candidates import get_sign_candidates_for_area, get_route_summary_for_area, get_area_stats
from services._timing import format_server_timing
from services import field_photos as fp_svc
from services.sign_excel import build_manufacturing_workbook
from services.sign_pdf import build_field_pdf
from services.route_validation_report import build_validation_workbook
from services.route_service import snap_point_to_full_route
from services.route_service import point_on_route_km_and_geom
from services.validators import get_validator_registry
from collections import defaultdict
from services.database import db_connection, get_route_schema, get_teig_schema, quote_identifier, ROUTE_SCHEMA
from services.excel_report import generate_owners_excel_from_data
from services.geometry_owner_service import get_owners_for_linestring, GeometryOwnerError
from services.point_matrikkel_service import get_matrikkelenhet_for_point, PointMatrikkelError
from api.auth import require_feature
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
    _: Dict = Depends(require_feature("grunneier")),
):
    """
    Download Excel report with owners information from matrikkelenhet_vector.

    This endpoint can be used for:
    - Drawn lines (send geometry and get matrikkelenhet_vector first)
    - Selected links (send link_ids and get matrikkelenhet_vector first)
    - Any custom geometry

    Access is gated by the `grunneier` feature flag (OAuth session). The legacy
    require_shared_login (HTTP Basic) was dropped — the signs_app OAuth client
    never sends Basic credentials, so it always 401'd.
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
async def get_geometry_owners(
    request: GeometryOwnerRequest,
    _: Dict = Depends(require_feature("grunneier")),
):
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
    _: Dict = Depends(require_feature("grunneier")),
):
    """
    Get matrikkelenhet (teig polygon) for a point coordinate.

    Accepts a point (latitude, longitude) in WGS84 and returns the teig polygon
    that contains the point, along with matrikkelenhet information.

    Owner information is always fetched: access is already gated by the
    `grunneier` feature flag (require_feature above), which only passes for an
    authenticated OAuth session holding the flag. (The legacy get_optional_user
    dependency checked HTTP Basic credentials that the signs_app OAuth client
    never sends, so owners silently came back empty — see Phase 3.)

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
    - owners: Owner information
    """
    try:
        result = get_matrikkelenhet_for_point(request.lat, request.lon, include_owners=True)

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
    anchor_geom = None
    with db_connection() as conn:
        anchor_coords = get_anchor_node_coords(conn, anchor_id)
        anchor_geom = get_anchor_node_geometry(conn, anchor_id)

    if not anchor_geom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Anchor node {anchor_id} not found or has no geometry. Geometry is required for synchronization."
        )

    with op_db_connection() as conn:
        row = upsert_endpoint_name(
            conn,
            anchor_node_id=anchor_id,
            name=request.name,
            source_type=request.source_type,
            geom=anchor_geom,
            rutenummer=request.rutenummer,
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
                "f.oppdateringsdato",
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
                    oppd = row.get("oppdateringsdato")
                    oppdateringsdato = oppd.isoformat() if oppd is not None and hasattr(oppd, "isoformat") else (str(oppd) if oppd is not None else None)
                    segments_dict[objid] = {
                        "objid": objid,
                        "object_uuid": row.get("object_uuid"),
                        "routes": [],
                        "length_meters": float(row["length_meters"]) if row.get("length_meters") is not None else None,
                        "geometry": None,
                        "oppdateringsdato": oppdateringsdato,
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
                    geometry=segment_data["geometry"],
                    oppdateringsdato=segment_data.get("oppdateringsdato"),
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


@router.get("/routes/statistics", response_model=RoutesStatisticsResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_routes_statistics_endpoint(
    prefix: Annotated[Optional[str], Query(description="Filter by route number prefix (e.g., 'bre', 'jot')")] = None,
    vedlikeholdsansvarlig: Annotated[Optional[str], Query(description="Filter by organization (pattern match)")] = None,
    bbox: Annotated[Optional[str], Query(description="Bounding box as 'xmin,ymin,xmax,ymax' in WGS84")] = None,
) -> RoutesStatisticsResponse:
    """
    Get aggregate statistics for routes: total count, total km (sum of route lengths),
    and distinct km (sum of link lengths without double-counting overlapping links).

    At least one filter (prefix, vedlikeholdsansvarlig, or bbox) is required.
    """
    if not prefix and not vedlikeholdsansvarlig and not bbox:
        raise HTTPException(
            status_code=400,
            detail="At least one filter is required: prefix, vedlikeholdsansvarlig, or bbox"
        )
    try:
        bbox_tuple = None
        if bbox:
            try:
                bbox_tuple = parse_bbox(bbox)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid bbox format: {e}")

        with db_connection() as conn:
            stats = get_routes_statistics(
                conn,
                prefix=prefix,
                vedlikeholdsansvarlig=vedlikeholdsansvarlig,
                bbox=bbox_tuple,
            )
        return RoutesStatisticsResponse(**stats)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting route statistics: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error getting route statistics: {str(e)}"
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

            # Get endpoint names for routes using link topology (more reliable than geometry)
            if routes:
                rutenummer_list_for_endpoints = [r['rutenummer'] for r in routes]
                endpoint_placeholders = ','.join(['%s'] * len(rutenummer_list_for_endpoints))

                endpoint_query = f"""
                    WITH route_links_expanded AS (
                        SELECT
                            UNNEST(lwr.rutenummer_list) as rutenummer,
                            lwr.a_node,
                            lwr.b_node
                        FROM {schema_quoted}.links_with_routes lwr
                        WHERE lwr.rutenummer_list && ARRAY[{endpoint_placeholders}]
                    ),
                    route_nodes AS (
                        SELECT
                            rutenummer,
                            node_id,
                            COUNT(*) as occurrence_count
                        FROM (
                            SELECT rutenummer, a_node as node_id FROM route_links_expanded WHERE a_node IS NOT NULL
                            UNION ALL
                            SELECT rutenummer, b_node as node_id FROM route_links_expanded WHERE b_node IS NOT NULL
                        ) all_nodes
                        GROUP BY rutenummer, node_id
                    ),
                    route_endpoints AS (
                        SELECT
                            rutenummer,
                            array_agg(node_id ORDER BY node_id) FILTER (WHERE occurrence_count = 1) as endpoint_nodes
                        FROM route_nodes
                        GROUP BY rutenummer
                    )
                    SELECT
                        re.rutenummer,
                        re.endpoint_nodes[1] as first_node,
                        CASE
                            WHEN array_length(re.endpoint_nodes, 1) >= 2 THEN re.endpoint_nodes[array_length(re.endpoint_nodes, 1)]
                            ELSE re.endpoint_nodes[1]
                        END as last_node
                    FROM route_endpoints re
                    WHERE array_length(re.endpoint_nodes, 1) > 0
                """

                try:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(endpoint_query, rutenummer_list_for_endpoints)
                        endpoint_rows = cur.fetchall()

                    # Map endpoint nodes to routes
                    endpoint_map = {row['rutenummer']: row for row in endpoint_rows}
                    anchor_ids = []
                    for row in endpoint_rows:
                        if row.get("first_node") is not None:
                            anchor_ids.append(int(row["first_node"]))
                        if row.get("last_node") is not None:
                            anchor_ids.append(int(row["last_node"]))

                    # Get endpoint names from operational database (validated anchor names)
                    endpoint_overrides = {}
                    if anchor_ids:
                        with op_db_connection() as op_conn:
                            endpoint_overrides = get_endpoint_names_for_anchor_routes(
                                op_conn,
                                anchor_ids,
                                rutenummer_list_for_endpoints,
                            )

                    # Apply endpoint names to routes
                    for route in routes:
                        endpoint_info = endpoint_map.get(route['rutenummer'])
                        if endpoint_info:
                            override_map = endpoint_overrides.get(route["rutenummer"], {}) if endpoint_overrides else {}

                            # Get from name
                            first_node = endpoint_info.get("first_node")
                            last_node = endpoint_info.get("last_node")

                            # Only set names if we have different nodes (not a loop)
                            if first_node and last_node and first_node != last_node:
                                from_override = override_map.get(first_node)
                                to_override = override_map.get(last_node)

                                if from_override and from_override.get("name"):
                                    route["from_name"] = from_override.get("name")
                                if to_override and to_override.get("name"):
                                    route["to_name"] = to_override.get("name")
                            elif first_node:
                                # Single endpoint (loop route) - only set from_name
                                from_override = override_map.get(first_node)
                                if from_override and from_override.get("name"):
                                    route["from_name"] = from_override.get("name")
                except Exception as e:
                    # Endpoint lookup is optional, continue without it
                    print(f"Warning: Could not fetch endpoint names for bulk routes: {e}")
                    import traceback
                    traceback.print_exc()

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


@router.get("/signs/manufacturing/{area_code}.xlsx")
def get_manufacturing_xlsx(area_code: str):
    """Excel manufacturing list (one row per panel) for an area."""
    if not re.match(r"^[a-z]{2,5}$", area_code or ""):
        raise HTTPException(status_code=400, detail="Invalid area_code")
    try:
        with db_connection() as conn:
            data = build_manufacturing_workbook(conn, area_code)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=skilt-{area_code}.xlsx",
            },
        )
    except Exception as e:
        print(f"Error generating manufacturing.xlsx for {area_code}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generating manufacturing.xlsx: {e}")


@router.post("/signs/manufacturing/{area_code}.xlsx")
def post_manufacturing_xlsx(area_code: str, payload: Dict):
    """Excel manufacturing list filtered to a user-supplied selection.

    Body: {"panels": ["<sign_site_id>:<destination_anchor_node_id>", ...]}
    Empty / missing selection returns the same content as the GET variant.
    """
    if not re.match(r"^[a-z]{2,5}$", area_code or ""):
        raise HTTPException(status_code=400, detail="Invalid area_code")
    selection = (payload or {}).get("panels") or []
    if not isinstance(selection, list):
        raise HTTPException(status_code=400, detail="`panels` must be a list of strings")
    try:
        with db_connection() as conn:
            data = build_manufacturing_workbook(conn, area_code, selection=selection or None)
        suffix = "valgte" if selection else "alle"
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=skilt-{area_code}-{suffix}.xlsx"},
        )
    except Exception as e:
        print(f"Error generating filtered manufacturing.xlsx for {area_code}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generating manufacturing.xlsx: {e}")


@router.get("/signs/validation/{area_code}.xlsx")
def get_validation_xlsx(area_code: str):
    """Per-area route-validation report (one row per issue + a summary sheet).

    Runs the registered validators (services.validators) on every route in
    the area plus a ferry-/boat-track heuristic, and produces an XLSX
    suitable for forwarding to Kartverket. See services/route_validation_report.py.
    """
    if not re.match(r"^[a-z]{2,5}$", area_code or ""):
        raise HTTPException(status_code=400, detail="Invalid area_code")
    try:
        with db_connection() as conn:
            data = build_validation_workbook(conn, area_code)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=rutevalidering-{area_code}.xlsx"},
        )
    except Exception as e:
        print(f"Error generating validation.xlsx for {area_code}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generating validation.xlsx: {e}")


@router.get("/signs/field-pdf/{area_code}.pdf")
def get_field_pdf(area_code: str):
    """Field PDF for an area — one A4 page per sign site with map snippet,
    route memberships, endpoint distances, panels, and nearby photos."""
    if not re.match(r"^[a-z]{2,5}$", area_code or ""):
        raise HTTPException(status_code=400, detail="Invalid area_code")
    try:
        with db_connection() as conn, op_db_connection() as op_conn:
            data = build_field_pdf(conn, op_conn, area_code)
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=feltkart-{area_code}.pdf"},
        )
    except Exception as e:
        print(f"Error generating field-pdf for {area_code}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generating field-pdf: {e}")


@router.post("/signs/field-pdf/{area_code}.pdf")
def post_field_pdf(area_code: str, payload: Dict):
    """Field PDF filtered to a selection. Body matches the Excel POST shape:
    ``{"panels": ["<sign_site_id>:<destination_anchor_node_id>:<first_link_id>", ...]}``.
    Empty / missing selection returns the same content as the GET variant."""
    if not re.match(r"^[a-z]{2,5}$", area_code or ""):
        raise HTTPException(status_code=400, detail="Invalid area_code")
    selection = (payload or {}).get("panels") or []
    if not isinstance(selection, list):
        raise HTTPException(status_code=400, detail="`panels` must be a list of strings")
    try:
        with db_connection() as conn, op_db_connection() as op_conn:
            data = build_field_pdf(conn, op_conn, area_code, selection=selection or None)
        suffix = "valgte" if selection else "alle"
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=feltkart-{area_code}-{suffix}.pdf"},
        )
    except Exception as e:
        print(f"Error generating filtered field-pdf for {area_code}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generating field-pdf: {e}")


def _validate_area_code(area_code: str) -> None:
    if not re.match(r"^[a-z]{2,5}$", area_code or ""):
        raise HTTPException(status_code=400, detail="Invalid area_code")


@router.get("/signs/placenames")
async def signs_app_nearby_placenames(
    lon: Annotated[float, Query(description="WGS84 longitude")],
    lat: Annotated[float, Query(description="WGS84 latitude")],
    radius: Annotated[float, Query(ge=10.0, le=5000.0, description="Search radius (m)")] = 500.0,
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
):
    """Nearest stedsnavn + ruteinfopunkt around a point.

    Same shape as `/v1/anchors/{anchor_id}/placenames` but takes coordinates
    instead of an anchor id — used by the signs_app's NamePicker for manual
    signs (which have no anchor_node_id).
    """
    try:
        with db_connection() as conn:
            candidates = list_placename_candidates(conn, lon, lat, search_radius_meters=radius, limit=limit)
            facilities = list_ruteinfopunkt_facilities(conn, lon, lat, search_radius_meters=radius, limit=limit)
        return {
            "lon": lon,
            "lat": lat,
            "radius_meters": radius,
            "candidates": [
                {
                    "name": c["name"],
                    "source_type": c["source"],
                    "source_id": c.get("source_id"),
                    "distance_meters": c.get("distance_meters"),
                    "tilrettelegging": c.get("tilrettelegging"),
                }
                for c in candidates
            ],
            "facilities": [
                {
                    "name": f["name"],
                    "source_id": f.get("source_id"),
                    "distance_meters": f.get("distance_meters"),
                    "tilrettelegging": f.get("tilrettelegging"),
                }
                for f in facilities
            ],
        }
    except Exception as e:
        print(f"Error getting nearby placenames: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error getting nearby placenames: {e}")


@router.post("/signs/anchors/{anchor_id}/name")
async def signs_app_set_anchor_name(
    anchor_id: int,
    payload: Dict,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Edit the anchor's display name from the signs_app.

    Upserts into ops.endpoint_names with source_type='signs_app'. The next
    /v1/signs/candidates fetch picks the new name up automatically (it's the
    same name resolver the sign-report uses).

    Body: { "name": "Sotabu" }
    """
    name = (payload or {}).get("name")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=400, detail="`name` is required")
    name = name.strip()
    with db_connection() as conn:
        coords = get_anchor_node_coords(conn, anchor_id)
        geom = get_anchor_node_geometry(conn, anchor_id)
    if not geom:
        raise HTTPException(status_code=404, detail=f"Anchor {anchor_id} not found")
    with op_db_connection() as op_conn:
        row = upsert_endpoint_name(
            op_conn,
            anchor_node_id=anchor_id,
            name=name,
            source_type="signs_app",
            geom=geom,
            rutenummer=None,  # global (any-route) name
            validated_by=x_user or "anonymous",
            anchor_lon=(coords or {}).get("lon"),
            anchor_lat=(coords or {}).get("lat"),
        )
    return {"anchor_node_id": anchor_id, "name": row.get("name", name)}


@router.patch("/signs/sites/{sign_site_id}/panels/{destination_anchor_node_id}/edit")
async def signs_app_patch_panel(
    sign_site_id: int,
    destination_anchor_node_id: int,
    payload: Dict,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Per-panel override: color, direction, displayed km, custom destination name.

    Stored on ops.sign_site_skilt, keyed by (sign_site_id, anchor_node_id).
    Only keys present in the payload are written; unknown keys are ignored.
    """
    updates: Dict = {}
    if "color" in payload:
        color = payload["color"]
        if color not in (None, "trehvit", "grønn"):
            raise HTTPException(status_code=400, detail="color must be 'trehvit' or 'grønn'")
        updates["skiltfarge"] = color
    if "direction" in payload:
        direction = payload["direction"]
        if direction is not None and not isinstance(direction, str):
            raise HTTPException(status_code=400, detail="direction must be a string or null")
        updates["direction"] = direction
    if "distance_km" in payload:
        km = payload["distance_km"]
        if km is None:
            updates["distance_meters"] = None
        else:
            try:
                updates["distance_meters"] = float(km) * 1000.0
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="distance_km must be numeric")
    if "destination_name" in payload:
        dn = payload["destination_name"]
        if dn is not None and not isinstance(dn, str):
            raise HTTPException(status_code=400, detail="destination_name must be a string or null")
        updates["destination_name"] = dn.strip() if isinstance(dn, str) else None
    if not updates:
        raise HTTPException(status_code=400, detail="no editable fields in payload")
    first_link_id_raw = payload.get("first_link_id")
    first_link_id: Optional[int] = None
    if first_link_id_raw is not None:
        try:
            first_link_id = int(first_link_id_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="first_link_id must be an integer")
    with op_db_connection() as op_conn:
        row = patch_sign_site_skilt(
            op_conn,
            sign_site_id=sign_site_id,
            anchor_node_id=destination_anchor_node_id,
            updates=updates,
            updated_by=x_user or "anonymous",
            first_link_id=first_link_id,
        )
    if row is None:
        raise HTTPException(status_code=500, detail="failed to write panel override")
    return row


@router.post("/signs/candidates/{area_code}/manual")
async def signs_app_create_manual_sign(
    area_code: str,
    payload: Dict,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Create a manual sign site at an arbitrary point along one or more routes.

    Body: {
      "rutenummer_list": ["bre21", "bre62"],   # preferred — list of routes the
                                               # sign belongs to (shared segment)
      "rutenummer": "bre6",                    # legacy single — equivalent to a
                                               # list of one
      "lon": 7.5, "lat": 61.7,
      "name": "Bridge"
    }

    The point is snapped to the *first* route's geometry (they share the segment,
    so the snap result is essentially identical across routes); we record
    `route_km` along that first route so panels for each route can be computed
    at read time. `rutenummer_list` stores the full set; the legacy
    `rutenummer` column gets the first element for back-compat.
    """
    _validate_area_code(area_code)
    body = payload or {}
    raw_list = body.get("rutenummer_list")
    single = body.get("rutenummer")
    # Normalise: accept either {rutenummer_list:[...]} or {rutenummer:"..."}.
    if isinstance(raw_list, list) and raw_list:
        rutenummer_list = [str(r).strip() for r in raw_list if isinstance(r, str) and r.strip()]
    elif isinstance(single, str) and single.strip():
        rutenummer_list = [single.strip()]
    else:
        raise HTTPException(status_code=400, detail="`rutenummer_list` (or legacy `rutenummer`) is required")
    if not rutenummer_list:
        raise HTTPException(status_code=400, detail="rutenummer_list cannot be empty")
    lon = body.get("lon")
    lat = body.get("lat")
    name = body.get("name")
    if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
        raise HTTPException(status_code=400, detail="`lon` and `lat` (numbers) are required")
    # When the click sits on a shared segment we snap on EVERY listed route
    # and pick whichever lands closest to the click. snap_point_to_full_route
    # operates on `stiflyt.routes.route_geometry` (the full MultiLineString),
    # so disconnected segments no longer teleport the marker to the longest
    # connected portion.
    try:
        with db_connection() as conn:
            snapped_per_route = []
            for rn in rutenummer_list:
                s = snap_point_to_full_route(conn, rn, float(lon), float(lat))
                if s is not None:
                    snapped_per_route.append((rn, s))
        if not snapped_per_route:
            raise HTTPException(status_code=404, detail=f"Could not snap to any of {rutenummer_list}")
        snapped_per_route.sort(key=lambda t: t[1][2])  # by distance_to_click
        primary_route, (route_km, geom_wkt, _dist_m) = snapped_per_route[0]
        # Reorder rutenummer_list so primary_route is first (used as the legacy
        # `rutenummer` column).
        rutenummer_list = [primary_route] + [r for r in rutenummer_list if r != primary_route]
        with op_db_connection() as op_conn:
            site_code = allocate_site_code(op_conn, area_code)
            from services.operational_store import OP_SCHEMA as _OP
            schema_quoted = quote_identifier(_OP)
            with op_conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    INSERT INTO {schema_quoted}.sign_sites
                        (rutenummer, rutenummer_list, route_km, geom, anchor_node_id, name,
                         area_code, status, site_code, updated_by)
                    VALUES (%s, %s, %s, ST_SetSRID(ST_GeomFromText(%s), 25833), NULL, %s,
                            %s, 'accepted', %s, %s)
                    RETURNING id, site_code, status, area_code, rutenummer, rutenummer_list,
                              route_km, name;
                    """,
                    (
                        primary_route,
                        rutenummer_list,
                        route_km,
                        geom_wkt,
                        name,
                        area_code,
                        site_code,
                        x_user or "anonymous",
                    ),
                )
                return dict(cur.fetchone())
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating manual sign: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating manual sign: {e}")


@router.delete("/signs/sites/{sign_site_id}", status_code=204)
async def delete_sign_site_endpoint(
    sign_site_id: int,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Hard-delete a sign site. For anchor-based sites this also drops the
    accept/reject state so the anchor reappears as a fresh proposed candidate.
    For manual sites the sign and its panels go away entirely."""
    try:
        with op_db_connection() as op_conn:
            deleted = delete_sign_site(op_conn, sign_site_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Sign site {sign_site_id} not found")
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting sign site {sign_site_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error deleting sign site: {e}")


@router.post("/signs/candidates/{area_code}/anchors/{anchor_node_id}/accept")
async def accept_sign_candidate_endpoint(
    area_code: str,
    anchor_node_id: int,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Persist a proposed candidate as an accepted sign site, allocating a site code."""
    _validate_area_code(area_code)
    try:
        with db_connection() as conn:
            geom_wkt = get_anchor_node_geometry(conn, anchor_node_id)
            if geom_wkt is None:
                raise HTTPException(status_code=404, detail=f"Anchor {anchor_node_id} not found")
            from services.operational_store import get_endpoint_names_for_anchors as _names
            with op_db_connection() as op_conn:
                names = _names(op_conn, [anchor_node_id])
                resolved_name = (names.get(anchor_node_id) or {}).get("name")
                row = accept_sign_candidate(
                    op_conn,
                    area_code=area_code,
                    anchor_node_id=anchor_node_id,
                    geom_wkt_25833=geom_wkt,
                    name=resolved_name,
                    updated_by=x_user,
                )
        return row
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error accepting candidate {area_code}/{anchor_node_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error accepting candidate: {e}")


@router.post("/signs/candidates/{area_code}/anchors/{anchor_node_id}/reject")
async def reject_sign_candidate_endpoint(
    area_code: str,
    anchor_node_id: int,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Mark an anchor as rejected (won't appear as 'proposed' next load)."""
    _validate_area_code(area_code)
    try:
        with db_connection() as conn:
            geom_wkt = get_anchor_node_geometry(conn, anchor_node_id)
            if geom_wkt is None:
                raise HTTPException(status_code=404, detail=f"Anchor {anchor_node_id} not found")
            from services.operational_store import get_endpoint_names_for_anchors as _names
            with op_db_connection() as op_conn:
                names = _names(op_conn, [anchor_node_id])
                resolved_name = (names.get(anchor_node_id) or {}).get("name")
                row = reject_sign_candidate(
                    op_conn,
                    area_code=area_code,
                    anchor_node_id=anchor_node_id,
                    geom_wkt_25833=geom_wkt,
                    name=resolved_name,
                    updated_by=x_user,
                )
        return row
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error rejecting candidate {area_code}/{anchor_node_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error rejecting candidate: {e}")


@router.get("/signs/area/{area_code}/routes")
async def get_signs_area_route_summary(area_code: str, response: Response) -> Dict:
    """Per-route summary for the signs_app route hover popup.

    Returns rutenummer + start_name, end_name and total length (corrected km).
    Lightweight (~80 ms on bre) so the frontend can fetch it once per area
    and look up route metadata client-side when rendering hovers.

    Emits a Server-Timing header so per-phase costs show up in browser
    DevTools (Network → request → Timing).
    """
    _validate_area_code(area_code)
    try:
        timings: list = []
        with db_connection() as conn:
            result = get_route_summary_for_area(conn, area_code, timings=timings)
        if timings:
            response.headers["Server-Timing"] = format_server_timing(timings)
            response.headers["Access-Control-Expose-Headers"] = "Server-Timing"
        return result
    except Exception as e:
        print(f"Error getting route summary for {area_code}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error getting route summary: {e}")


@router.get("/signs/area/{area_code}/stats")
async def get_signs_area_stats(area_code: str) -> Dict:
    """Headline numbers for the area report modal.

    Cheap — single link-fetch + sum. Other report fields (sign counts,
    panel counts, status breakdown) are derived client-side from the
    /candidates response the frontend already has in memory.
    """
    _validate_area_code(area_code)
    try:
        with db_connection() as conn:
            return get_area_stats(conn, area_code)
    except Exception as e:
        print(f"Error getting area stats for {area_code}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error getting area stats: {e}")


@router.get("/signs/area/{area_code}/validation")
async def get_area_validation(area_code: str, refresh: bool = False):
    """Per-route validation summary for the area (Problemruter list).

    Running all validators across an area takes minutes, so the result is
    cached in-process and recomputed in the background. Returns
    `{status: computing|ready|error, computed_at, routes, ...}`; the UI polls
    until `status == "ready"`. `?refresh=1` forces a recompute.
    """
    _validate_area_code(area_code)
    try:
        from services.route_validation_report import get_area_validation_cached
        snap = get_area_validation_cached(area_code, refresh=refresh)
        return {"area_code": area_code, **snap}
    except Exception as e:
        print(f"Error getting area validation for {area_code}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error getting area validation: {e}")


# ---------------------------------------------------------------------------
# Route annotations — rutebok diary, inspection, dugnad, work-marker
# ---------------------------------------------------------------------------


def _validate_rutenummer(rutenummer: str) -> None:
    # rutenummer is canonically `<area_prefix><number>` (e.g. "bre1"); also
    # allow the `<area><digits><letter?>` Kartverket suffix forms. Anything
    # outside [a-z0-9_] is rejected.
    if not re.match(r"^[a-z0-9_]+$", rutenummer or "") or len(rutenummer) > 32:
        raise HTTPException(status_code=400, detail="Invalid rutenummer")


@router.get("/routes/{area_code}/{rutenummer}/annotations")
async def list_route_annotations(
    area_code: str,
    rutenummer: str,
    kind: Optional[str] = None,
    include_resolved: bool = True,
):
    """List rutebok/inspection/dugnad/work entries for one route.

    `kind=` accepts a comma-separated list (e.g. `kind=diary,inspection`).
    """
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    kinds = [k.strip() for k in kind.split(",")] if kind else None
    try:
        with op_db_connection() as op_conn:
            from services.route_annotations import list_for_route
            rows = list_for_route(
                op_conn, area_code, rutenummer,
                kinds=kinds, include_resolved=include_resolved,
            )
        return {"area_code": area_code, "rutenummer": rutenummer, "annotations": rows}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error listing route annotations: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error listing route annotations: {e}")


@router.get("/routes/{area_code}/work-markers")
async def list_work_markers(
    area_code: str,
    include_resolved: bool = False,
):
    """All work_* annotations with geom across the area — the map-layer feed."""
    _validate_area_code(area_code)
    try:
        with op_db_connection() as op_conn:
            from services.route_annotations import list_work_markers_for_area
            rows = list_work_markers_for_area(
                op_conn, area_code, include_resolved=include_resolved,
            )
        return {"area_code": area_code, "markers": rows}
    except Exception as e:
        print(f"Error listing work markers: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error listing work markers: {e}")


@router.post("/routes/{area_code}/{rutenummer}/annotations")
async def create_route_annotation(
    area_code: str,
    rutenummer: str,
    payload: Dict,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Create a new annotation for the route.

    Body fields:
    - kind (required): diary | inspection | dugnad | work_klipping |
      work_bridge | work_klopper | work_other
    - title, body, occurred_at, position_along_m, lon, lat (all optional)
    """
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    kind = payload.get("kind")
    if not kind:
        raise HTTPException(status_code=400, detail="`kind` is required")
    try:
        with op_db_connection() as op_conn:
            from services.route_annotations import insert
            row = insert(
                op_conn,
                area_code=area_code,
                rutenummer=rutenummer,
                kind=kind,
                title=payload.get("title"),
                body=payload.get("body"),
                occurred_at=payload.get("occurred_at"),
                position_along_m=payload.get("position_along_m"),
                lon=payload.get("lon"),
                lat=payload.get("lat"),
                recorded_by=x_user,
            )
        return row
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error creating route annotation: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating route annotation: {e}")


@router.patch("/route-annotations/{annotation_id}")
async def update_route_annotation(
    annotation_id: int,
    payload: Dict,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Patch an annotation (mark resolved, edit body/title, move marker, etc.)."""
    try:
        with op_db_connection() as op_conn:
            from services.route_annotations import update
            row = update(op_conn, annotation_id, payload or {})
        if row is None:
            raise HTTPException(status_code=404, detail=f"Annotation {annotation_id} not found")
        return row
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error updating route annotation {annotation_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error updating route annotation: {e}")


@router.delete("/route-annotations/{annotation_id}", status_code=204)
async def delete_route_annotation(
    annotation_id: int,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    try:
        with op_db_connection() as op_conn:
            from services.route_annotations import delete
            deleted = delete(op_conn, annotation_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Annotation {annotation_id} not found")
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting route annotation {annotation_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error deleting route annotation: {e}")


# ---------------------------------------------------------------------------
# Route corrections — link exclusions + single-route validation
# ---------------------------------------------------------------------------


@router.get("/routes/{area_code}/{rutenummer}/validation")
async def get_route_validation(area_code: str, rutenummer: str):
    """Run all validators on one route and return findings.

    ROUTE_HAS_LOOP (when present) carries the loop's arm decomposition in its
    metadata (`arm_groups`, `fork_nodes`, `decomposable`), which the UI uses to
    highlight arms and offer per-arm exclusion.
    """
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    try:
        with db_connection() as conn:
            from services.route_corrections import validate_route
            result = validate_route(conn, rutenummer)
        return {"area_code": area_code, **result}
    except Exception as e:
        print(f"Error validating route {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error validating route: {e}")


@router.get("/routes/{area_code}/{rutenummer}/link-exclusions")
async def list_route_link_exclusions(area_code: str, rutenummer: str):
    """Current link exclusions for the route."""
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    try:
        with op_db_connection() as op_conn:
            from services.route_corrections import list_exclusions
            rows = list_exclusions(op_conn, rutenummer)
        return {"area_code": area_code, "rutenummer": rutenummer, "exclusions": rows}
    except Exception as e:
        print(f"Error listing link exclusions for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error listing link exclusions: {e}")


@router.post("/routes/{area_code}/{rutenummer}/link-exclusions")
async def create_route_link_exclusions(
    area_code: str,
    rutenummer: str,
    payload: Dict,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Exclude one or more links from the route.

    Body: `{"link_ids": [int, ...], "reason": str?, "comment": str?}`.
    Returns the route's full exclusion set after the write.
    """
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    link_ids = (payload or {}).get("link_ids")
    if not isinstance(link_ids, list) or not link_ids:
        raise HTTPException(status_code=400, detail="`link_ids` must be a non-empty list")
    try:
        with op_db_connection() as op_conn:
            from services.route_corrections import add_exclusions
            rows = add_exclusions(
                op_conn,
                rutenummer=rutenummer,
                link_ids=link_ids,
                reason=payload.get("reason"),
                comment=payload.get("comment"),
                updated_by=x_user,
            )
        return {"area_code": area_code, "rutenummer": rutenummer, "exclusions": rows}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error creating link exclusions for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating link exclusions: {e}")


@router.delete("/routes/{area_code}/{rutenummer}/link-exclusions")
async def delete_route_link_exclusions(
    area_code: str,
    rutenummer: str,
    link_ids: Optional[str] = Query(None, description="Comma-separated link_ids; omit to clear all"),
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Remove exclusions for the route. Without `link_ids`, clears all of them."""
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    ids: Optional[List[int]] = None
    if link_ids:
        try:
            ids = [int(x) for x in link_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="`link_ids` must be comma-separated integers")
    try:
        with op_db_connection() as op_conn:
            from services.route_corrections import remove_exclusions
            deleted = remove_exclusions(op_conn, rutenummer=rutenummer, link_ids=ids)
        return {"area_code": area_code, "rutenummer": rutenummer, "deleted": deleted}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error deleting link exclusions for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error deleting link exclusions: {e}")


@router.get("/routes/{area_code}/{rutenummer}/link-bridges")
async def list_route_link_bridges(area_code: str, rutenummer: str):
    """Current bridges (synthetic connectors) for the route."""
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    try:
        with op_db_connection() as op_conn:
            from services.route_corrections import list_bridges
            rows = list_bridges(op_conn, rutenummer)
        return {"area_code": area_code, "rutenummer": rutenummer, "bridges": rows}
    except Exception as e:
        print(f"Error listing link bridges for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error listing link bridges: {e}")


@router.post("/routes/{area_code}/{rutenummer}/link-bridges")
async def create_route_link_bridge(
    area_code: str,
    rutenummer: str,
    payload: Dict,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Bridge two nodes of a disconnected route.

    Body: `{"a_node": int, "b_node": int, "reason": str?, "comment": str?}`.
    The two nodes must belong to the route and currently sit in different
    components. Returns the route's full bridge set after the write.
    """
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    a_node = (payload or {}).get("a_node")
    b_node = (payload or {}).get("b_node")
    if not isinstance(a_node, int) or not isinstance(b_node, int):
        raise HTTPException(status_code=400, detail="`a_node` and `b_node` (integers) are required")
    try:
        from services.route_corrections import route_node_components, add_bridge
        with db_connection() as conn:
            node_comp = route_node_components(conn, rutenummer)
        if a_node not in node_comp or b_node not in node_comp:
            raise HTTPException(status_code=400, detail="Both nodes must belong to the route")
        if node_comp[a_node] == node_comp[b_node]:
            raise HTTPException(status_code=400, detail="Nodes are already connected; a bridge would create a loop")
        with op_db_connection() as op_conn:
            rows = add_bridge(
                op_conn,
                rutenummer=rutenummer,
                a_node=a_node,
                b_node=b_node,
                reason=payload.get("reason"),
                comment=payload.get("comment"),
                updated_by=x_user,
            )
        return {"area_code": area_code, "rutenummer": rutenummer, "bridges": rows}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error creating link bridge for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating link bridge: {e}")


@router.delete("/routes/{area_code}/{rutenummer}/link-bridges")
async def delete_route_link_bridges(
    area_code: str,
    rutenummer: str,
    nodes: Optional[str] = Query(None, description="'a-b' node pair; omit to clear all"),
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Remove bridges for the route. Without `nodes`, clears all of them.
    `nodes=a-b` removes one specific bridge."""
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    pairs: Optional[List[tuple]] = None
    if nodes:
        try:
            a_s, b_s = nodes.split("-")
            pairs = [(int(a_s), int(b_s))]
        except ValueError:
            raise HTTPException(status_code=400, detail="`nodes` must be 'a-b' integers")
    try:
        with op_db_connection() as op_conn:
            from services.route_corrections import remove_bridges
            deleted = remove_bridges(op_conn, rutenummer=rutenummer, pairs=pairs)
        return {"area_code": area_code, "rutenummer": rutenummer, "deleted": deleted}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error deleting link bridges for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error deleting link bridges: {e}")


@router.get("/routes/{area_code}/{rutenummer}/photos")
async def get_route_photos(area_code: str, rutenummer: str, radius_m: float = 75.0):
    """Photos near the route's geometry (derived by proximity, not stored).

    Radius is in metres against the corrected route line, so it reflects
    exclusions/bridges and is accurate at northern latitudes.
    """
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    try:
        with db_connection() as conn:
            rows = fp_svc.list_photos_near_route(conn, area_code, rutenummer, radius_m=radius_m)
        return {"area_code": area_code, "rutenummer": rutenummer, "photos": rows}
    except Exception as e:
        print(f"Error getting route photos for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error getting route photos: {e}")


@router.get("/routes/{area_code}/{rutenummer}/gpx-comparison")
async def get_route_gpx_comparison(area_code: str, rutenummer: str):
    """Compare uploaded GPX tracks to this route's mapped line — the empirical
    walked-vs-mapped distance factor (validated the move from ×1.125 to ×1.05) plus
    per-track coverage."""
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    try:
        from services import gpx_tracks as gpx_svc
        with db_connection() as conn:
            result = gpx_svc.compare_to_route(conn, area_code, rutenummer)
        with op_db_connection() as op_conn:
            from services.sign_candidates import get_distance_correction_factor
            result["assumed_factor"] = get_distance_correction_factor(op_conn, area_code)
        return {"area_code": area_code, **result}
    except Exception as e:
        print(f"Error comparing gpx for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error comparing gpx: {e}")


@router.get("/routes/{area_code}/{rutenummer}/kort", response_class=HTMLResponse)
async def get_route_card(area_code: str, rutenummer: str):
    """Per-route summary page ("rutekort"): map + elevation + Naismith +
    GPS-fasit + photos + dagbok + work markers + validation, no JS, print-friendly.
    Shareable URL within the OK; user prints to PDF via the browser."""
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    try:
        from services import route_card
        with db_connection() as conn, op_db_connection() as op_conn:
            data = route_card.gather(conn, op_conn, area_code, rutenummer)
        return HTMLResponse(content=route_card.render_html(data))
    except Exception as e:
        print(f"Error rendering route card for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error rendering route card: {e}")


@router.get("/routes/{area_code}/{rutenummer}/dagbok.xlsx")
async def get_route_dagbok_xlsx(area_code: str, rutenummer: str):
    """Diary entries for the route as a one-sheet Excel."""
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    try:
        from services import route_card
        from services.route_annotations import list_for_route
        with op_db_connection() as op_conn:
            anns = list_for_route(op_conn, area_code, rutenummer, kinds=["diary"])
        data = route_card.build_dagbok_xlsx(anns, area_code, rutenummer)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=dagbok-{area_code}-{rutenummer}.xlsx"},
        )
    except Exception as e:
        print(f"Error generating dagbok.xlsx for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generating dagbok.xlsx: {e}")


@router.get("/routes/{area_code}/{rutenummer}/elevation")
async def get_route_elevation(area_code: str, rutenummer: str, refresh: bool = False):
    """Elevation profile for the route from Kartverket Høydedata (cached).

    Computes on a cache miss (~2.7s — samples the route against the /punkt API),
    then serves instantly. `?refresh=1` forces a re-sample.
    """
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    try:
        with op_db_connection() as conn:
            from services.elevation import get_elevation
            prof = get_elevation(conn, rutenummer, refresh=refresh)
        if prof is None:
            raise HTTPException(status_code=404, detail="No geometry for route")
        return {"area_code": area_code, **prof}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting elevation for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error getting elevation: {e}")


@router.get("/routes/{area_code}/{rutenummer}/metadata-override")
async def get_route_metadata_override(area_code: str, rutenummer: str):
    """Current metadata override for the route (rutenavn / vedlikeholdsansvarlig
    / rutetype / gradering), or null if none."""
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    try:
        with op_db_connection() as op_conn:
            from services.route_corrections import get_metadata_override
            ov = get_metadata_override(op_conn, rutenummer)
        return {"area_code": area_code, "rutenummer": rutenummer, "override": ov}
    except Exception as e:
        print(f"Error getting metadata override for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error getting metadata override: {e}")


@router.put("/routes/{area_code}/{rutenummer}/metadata-override")
async def put_route_metadata_override(
    area_code: str,
    rutenummer: str,
    payload: Dict,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Set the route's canonical metadata. Body may include any of
    `rutenavn`, `vedlikeholdsansvarlig`, `rutetype`, `gradering`, `comment`.
    Blank/omitted fields leave Kartverket's value; if all four are blank the
    override is removed. Returns the resulting override (or null)."""
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    payload = payload or {}
    try:
        with op_db_connection() as op_conn:
            from services.route_corrections import set_metadata_override
            ov = set_metadata_override(
                op_conn,
                rutenummer=rutenummer,
                rutenavn=payload.get("rutenavn"),
                vedlikeholdsansvarlig=payload.get("vedlikeholdsansvarlig"),
                rutetype=payload.get("rutetype"),
                gradering=payload.get("gradering"),
                comment=payload.get("comment"),
                updated_by=x_user,
            )
        return {"area_code": area_code, "rutenummer": rutenummer, "override": ov}
    except Exception as e:
        print(f"Error setting metadata override for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error setting metadata override: {e}")


@router.delete("/routes/{area_code}/{rutenummer}/metadata-override")
async def delete_route_metadata_override(
    area_code: str,
    rutenummer: str,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Remove the route's metadata override (restore Kartverket values)."""
    _validate_area_code(area_code)
    _validate_rutenummer(rutenummer)
    try:
        with op_db_connection() as op_conn:
            from services.route_corrections import clear_metadata_override
            deleted = clear_metadata_override(op_conn, rutenummer)
        return {"area_code": area_code, "rutenummer": rutenummer, "deleted": deleted}
    except Exception as e:
        print(f"Error deleting metadata override for {rutenummer}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error deleting metadata override: {e}")


# ---------------------------------------------------------------------------
# GPX tracks — actually-walked overlay
# ---------------------------------------------------------------------------


@router.get("/gpx")
async def list_gpx_tracks(area: str):
    """All GPX tracks for an area (geometry as WGS84 GeoJSON for the map)."""
    _validate_area_code(area)
    try:
        with op_db_connection() as op_conn:
            from services import gpx_tracks as gpx_svc
            tracks = gpx_svc.list_tracks(op_conn, area)
        return {"area_code": area, "tracks": tracks}
    except Exception as e:
        print(f"Error listing gpx tracks for {area}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error listing gpx tracks: {e}")


@router.post("/gpx")
async def upload_gpx_track(
    area: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
    name: Annotated[Optional[str], Form()] = None,
    x_user: Optional[str] = Header(None, alias="X-User"),
) -> Dict:
    """Upload one GPX file; it's parsed to a track geometry and stored for the
    area. `name` falls back to the GPX's own name, then the filename."""
    _validate_area_code(area)
    try:
        raw = await file.read()
        from services import gpx_tracks as gpx_svc
        segments, gpx_name = gpx_svc.parse_gpx(raw)
        track_name = (name or "").strip() or gpx_name or (file.filename or "tur").rsplit(".", 1)[0]
        with op_db_connection() as op_conn:
            track = gpx_svc.insert_track(
                op_conn,
                area_code=area,
                name=track_name,
                segments=segments,
                uploaded_by=x_user,
            )
        return track
    except Exception as e:
        from services.gpx_tracks import GpxParseError
        if isinstance(e, GpxParseError):
            raise HTTPException(status_code=400, detail=str(e))
        print(f"Error uploading gpx for {area}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error uploading gpx: {e}")


@router.delete("/gpx/{track_id}", status_code=204)
async def delete_gpx_track(track_id: int, x_user: Optional[str] = Header(None, alias="X-User")):
    try:
        with op_db_connection() as op_conn:
            from services import gpx_tracks as gpx_svc
            deleted = gpx_svc.delete_track(op_conn, track_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"GPX track {track_id} not found")
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting gpx track {track_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error deleting gpx track: {e}")


# ---------------------------------------------------------------------------
# Field photos — uncoupled photo layer (sign documentation + route condition)
# ---------------------------------------------------------------------------


@router.post("/photos")
async def upload_photo(
    area: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
    caption: Annotated[Optional[str], Form()] = None,
    # FastAPI parses repeated `tags=foo&tags=bar` into a list via Form().
    tags: Annotated[List[str], Form()] = [],
) -> Dict:
    """Upload one photo. EXIF GPS is auto-extracted; photos without GPS
    get NULL lon/lat and surface in the "needs placement" tray until the
    user geotags them via PATCH.
    """
    _validate_area_code(area)
    try:
        raw = await file.read()
        storage = fp_svc.store_upload(
            area_code=area,
            raw_bytes=raw,
            filename=file.filename,
            mime_type=file.content_type,
        )
        with op_db_connection() as op_conn:
            row = fp_svc.insert_photo(
                op_conn,
                area_code=area,
                storage=storage,
                caption=caption,
                tags=tags,
                uploaded_by=None,
            )
        return row
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error uploading photo to {area}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error uploading photo: {e}")


@router.get("/photos")
async def list_photos(
    area: Annotated[str, Query(...)],
    pending: Annotated[Optional[bool], Query(description="True=only awaiting placement, False=only placed, omit=both")] = None,
) -> Dict:
    """List photos in an area. `pending=true` returns the "needs placement" tray;
    `pending=false` returns the placed photos (what the map layer draws)."""
    _validate_area_code(area)
    try:
        only_placed = None if pending is None else (not pending)
        with op_db_connection() as op_conn:
            rows = fp_svc.list_photos(op_conn, area, only_placed=only_placed)
        return {"area_code": area, "photos": rows, "count": len(rows)}
    except Exception as e:
        print(f"Error listing photos for {area}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error listing photos: {e}")


@router.get("/photos/{photo_id}/file")
async def get_photo_file(
    photo_id: int,
    size: Annotated[str, Query(pattern="^(thumb|display|original)$")] = "display",
):
    """Serve photo bytes. `size` picks the variant: thumb (200 px), display
    (1600 px JPEG), or original (the uploaded file, possibly HEIC)."""
    try:
        with op_db_connection() as op_conn:
            row = fp_svc.get_photo(op_conn, photo_id)
        if not row:
            raise HTTPException(status_code=404, detail="Photo not found")
        rel = row[{"thumb": "thumb_path", "display": "display_path", "original": "file_path"}[size]]
        path = fp_svc.resolve_path(rel)
        if not path.exists():
            raise HTTPException(status_code=404, detail="File missing on disk")
        # JPEGs for thumb/display; original keeps its uploaded mime.
        media_type = "image/jpeg" if size in ("thumb", "display") else (row.get("mime_type") or "application/octet-stream")
        return FileResponse(str(path), media_type=media_type)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error serving photo {photo_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error serving photo: {e}")


@router.get("/photos/thumbnails")
async def get_photo_thumbnails_bulk(
    area: Annotated[str, Query(...)],
    bbox: Annotated[
        Optional[str],
        Query(description="lng_min,lat_min,lng_max,lat_max — optional viewport filter"),
    ] = None,
) -> Dict:
    """Bulk-deliver thumbnail bytes for every placed photo in `area`, optionally
    clipped to a viewport `bbox`. The response is one JSON document carrying
    base64-encoded JPEGs so the map can register all thumbnails as map images
    in a single round trip instead of N per-photo GETs."""
    _validate_area_code(area)
    bbox_tuple: Optional[tuple] = None
    if bbox:
        try:
            parts = [float(x) for x in bbox.split(",")]
            if len(parts) != 4:
                raise ValueError("expected 4 comma-separated floats")
            bbox_tuple = (parts[0], parts[1], parts[2], parts[3])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid bbox: {e}")
    try:
        with op_db_connection() as op_conn:
            rows = fp_svc.list_placed_thumbnail_paths(op_conn, area, bbox_tuple)
        thumbs = []
        for r in rows:
            path = fp_svc.resolve_path(r["thumb_path"])
            if not path.exists():
                continue
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
            thumbs.append({"id": r["id"], "data": data})
        return {"area_code": area, "thumbs": thumbs, "count": len(thumbs)}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error bulk-loading thumbnails for {area}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error bulk-loading thumbnails: {e}")


@router.patch("/photos/{photo_id}")
async def patch_photo(
    photo_id: int,
    body: Dict[str, Any],
) -> Dict:
    """Update caption / tags / placement. Body keys:
      lon, lat        — manual geotag (both required together)
      caption         — string or null
      tags            — full replacement list (constrained vocabulary)
    """
    lon = body.get("lon")
    lat = body.get("lat")
    if (lon is None) != (lat is None):
        raise HTTPException(status_code=400, detail="lon and lat must be set together")
    caption = body.get("caption")
    clear_caption = "caption" in body and caption is None
    tags = body.get("tags")
    try:
        with op_db_connection() as op_conn:
            row = fp_svc.update_photo(
                op_conn,
                photo_id,
                lon=float(lon) if lon is not None else None,
                lat=float(lat) if lat is not None else None,
                caption=caption if not clear_caption else None,
                tags=list(tags) if isinstance(tags, list) else None,
                clear_caption=clear_caption,
            )
        if not row:
            raise HTTPException(status_code=404, detail="Photo not found")
        return row
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error patching photo {photo_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error patching photo: {e}")


@router.delete("/photos/{photo_id}")
async def delete_photo(photo_id: int) -> Dict:
    """Delete a photo row + best-effort delete its on-disk artifacts."""
    try:
        with op_db_connection() as op_conn:
            ok = fp_svc.delete_photo(op_conn, photo_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Photo not found")
        return {"deleted": photo_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting photo {photo_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error deleting photo: {e}")


@router.get("/signs/candidates/{area_code}")
async def get_sign_candidates(area_code: str, response: Response) -> Dict:
    """Auto-proposed sign sites + panels for an area (signs_app frontend).

    Returns every anchor in the area as a candidate sign site, with panels
    deduped by destination name, distances corrected by the area's factor (×1.05 default) and rounded
    per spec (<10 km floor to 0.5 km; >=10 km nearest int), and a 32V UTM
    formatted back-text.

    Emits a Server-Timing header so per-phase costs show up in browser
    DevTools (Network → request → Timing).
    """
    if not re.match(r"^[a-z]{2,5}$", area_code or ""):
        raise HTTPException(status_code=400, detail="Invalid area_code")
    try:
        timings: list = []
        with db_connection() as conn:
            result = get_sign_candidates_for_area(conn, area_code, timings=timings)
        if timings:
            response.headers["Server-Timing"] = format_server_timing(timings)
            response.headers["Access-Control-Expose-Headers"] = "Server-Timing"
        return result
    except Exception as e:
        print(f"Error getting sign candidates for {area_code}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error getting sign candidates: {e}")


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


@router.patch("/routes/{rutenummer}/signs/sites/{sign_site_id}/status")
async def upsert_sign_status_site(
    rutenummer: str,
    sign_site_id: int,
    request: SignStatusUpsertRequest,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Upsert sign status (pilretning, status/tilstand) for a sign_site."""
    with db_connection() as check_conn:
        routes, _ = get_routes_from_view(check_conn, rutenummer=rutenummer, limit=1, offset=0)
        if not routes:
            raise HTTPException(status_code=404, detail=f"Route '{rutenummer}' not found")
    with op_db_connection() as conn:
        site = get_sign_site_by_id(conn, sign_site_id)
        if not site or site.get("rutenummer") != rutenummer:
            raise HTTPException(status_code=404, detail=f"Sign site {sign_site_id} not found for route {rutenummer}")
    updated_by = x_user or "anonymous"
    last_inspected = None
    if request.last_inspected:
        try:
            last_inspected = datetime.fromisoformat(request.last_inspected.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
    ub = request.updated_by or updated_by
    with op_db_connection() as conn:
        if request.status_id is not None:
            row = update_sign_status_row_by_id(
                conn,
                request.status_id,
                sign_site_id,
                direction=request.direction,
                status=request.status,
                last_inspected=last_inspected,
                notes=request.notes,
                updated_by=ub,
            )
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Sign status id {request.status_id} not found for sign site {sign_site_id}",
                )
        else:
            row = upsert_sign_status(
                conn,
                direction=request.direction,
                status=request.status,
                last_inspected=last_inspected,
                notes=request.notes,
                updated_by=ub,
                sign_site_id=sign_site_id,
            )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to upsert sign status")
    return row


@router.patch("/signs/sites/{sign_site_id}", response_model=SignSiteResponse)
async def update_sign_site_endpoint(
    sign_site_id: int,
    request: SignSiteUpdateRequest,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Update sign site (name, back_text, send_to)."""
    updated_by = x_user or "anonymous"
    with op_db_connection() as conn:
        row = update_sign_site(
            conn,
            sign_site_id,
            name=request.name,
            back_text=request.back_text,
            send_to_name=request.send_to_name,
            send_to_address=request.send_to_address,
            skiltfarge=request.skiltfarge,
            updated_by=request.updated_by or updated_by,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Sign site {sign_site_id} not found")
    return SignSiteResponse(
        id=row["id"],
        rutenummer=row.get("rutenummer"),
        route_km=row.get("route_km"),
        lon=row.get("lon"),
        lat=row.get("lat"),
        anchor_node_id=row.get("anchor_node_id"),
        name=row.get("name"),
        back_text=row.get("back_text"),
        send_to_name=row.get("send_to_name"),
        send_to_address=row.get("send_to_address"),
        skiltfarge=row.get("skiltfarge"),
        created_at=row.get("created_at").isoformat() if row.get("created_at") else None,
        updated_at=row.get("updated_at").isoformat() if row.get("updated_at") else None,
    )


@router.patch("/signs/sites/{sign_site_id}/status")
async def upsert_sign_status_site_by_id(
    sign_site_id: int,
    request: SignStatusUpsertRequest,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Upsert sign status (pilretning, status) for a sign_site by ID. No route required; sign sites can belong to multiple routes."""
    updated_by = x_user or "anonymous"
    last_inspected = None
    if request.last_inspected:
        try:
            last_inspected = datetime.fromisoformat(request.last_inspected.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
    ub = request.updated_by or updated_by
    with op_db_connection() as conn:
        site = get_sign_site_by_id(conn, sign_site_id)
        if not site:
            raise HTTPException(status_code=404, detail=f"Sign site {sign_site_id} not found")
        if request.status_id is not None:
            row = update_sign_status_row_by_id(
                conn,
                request.status_id,
                sign_site_id,
                direction=request.direction,
                status=request.status,
                last_inspected=last_inspected,
                notes=request.notes,
                updated_by=ub,
            )
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Sign status id {request.status_id} not found for sign site {sign_site_id}",
                )
        else:
            row = upsert_sign_status(
                conn,
                direction=request.direction,
                status=request.status,
                last_inspected=last_inspected,
                notes=request.notes,
                updated_by=ub,
                sign_site_id=sign_site_id,
            )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to upsert sign status")
    return row


@router.get("/signs/sites/{sign_site_id}/destinations")
async def get_sign_site_destinations_endpoint(sign_site_id: int):
    """Get custom destinations (pil/skilt) for a sign site. Empty = use default."""
    with op_db_connection() as conn:
        site = get_sign_site_by_id(conn, sign_site_id)
        if not site:
            raise HTTPException(status_code=404, detail=f"Sign site {sign_site_id} not found")
        rows = get_sign_site_destinations(conn, sign_site_id)
    return {"sign_site_id": sign_site_id, "destinations": [{"anchor_node_id": r["anchor_node_id"], "display_order": r["display_order"]} for r in rows]}


@router.put("/signs/sites/{sign_site_id}/destinations")
async def set_sign_site_destinations_endpoint(
    sign_site_id: int,
    request: SignSiteDestinationsUpdateRequest,
):
    """Set custom destinations for a sign site. Empty list = use default (endpoints/topology)."""
    with op_db_connection() as conn:
        site = get_sign_site_by_id(conn, sign_site_id)
        if not site:
            raise HTTPException(status_code=404, detail=f"Sign site {sign_site_id} not found")
        dest_list = [{"anchor_node_id": d.anchor_node_id, "display_order": d.display_order} for d in request.destinations]
        rows = set_sign_site_destinations(conn, sign_site_id, dest_list)
    return {"sign_site_id": sign_site_id, "destinations": [{"anchor_node_id": r["anchor_node_id"], "display_order": r["display_order"]} for r in rows]}


@router.patch("/signs/sites/{sign_site_id}/destinations/{anchor_node_id}/skilt")
async def patch_sign_destination_skilt(
    sign_site_id: int,
    anchor_node_id: int,
    request: SignSiteSkiltPatchRequest,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Update skilt (retning, status, farge, avstand) for one destination on a sign site."""
    payload = request.model_dump(exclude_unset=True)
    manual_ub = payload.pop("updated_by", None)
    allowed = frozenset({"direction", "status", "skiltfarge", "distance_meters"})
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Send minst ett felt: direction, status, skiltfarge eller distance_meters.",
        )
    updated_by = manual_ub or x_user or "anonymous"
    with op_db_connection() as conn:
        site = get_sign_site_by_id(conn, sign_site_id)
        if not site:
            raise HTTPException(status_code=404, detail=f"Sign site {sign_site_id} not found")
        row = patch_sign_site_skilt(conn, sign_site_id, anchor_node_id, updates, updated_by=updated_by)
    if not row:
        raise HTTPException(status_code=500, detail="Failed to update skilt")
    ua = row.get("updated_at")
    return {
        "sign_site_id": sign_site_id,
        "anchor_node_id": anchor_node_id,
        "skilt": {
            "id": row.get("id"),
            "direction": row.get("direction"),
            "status": row.get("status"),
            "skiltfarge": row.get("skiltfarge"),
            "distance_meters": row.get("distance_meters"),
            "updated_at": ua.isoformat() if ua is not None and hasattr(ua, "isoformat") else ua,
        },
    }


@router.get("/signs/area/{area_code}/anchors/search")
async def search_anchors_endpoint(
    area_code: str,
    q: Annotated[str, Query(min_length=2, description="Navnesøk for ankerpunkt")],
    limit: Annotated[int, Query(ge=1, le=50)] = 15,
):
    """Search named anchor nodes in an area for picking a "through"-sign
    destination. Combines validated endpoint names (ops.endpoint_names) with
    anchor_nodes.navn. Returns [{anchor_node_id, name, lon, lat, source}]."""
    with op_db_connection() as opc:
        named = search_endpoint_names(opc, q, area_prefix=area_code, limit=limit * 3)
    with db_connection() as rc:
        navn_hits = search_anchor_nodes_by_navn(rc, q, limit=limit * 3)
        routable = routable_node_set(rc)
    merged: Dict[int, Dict] = {}
    for r in named:
        merged[r["anchor_node_id"]] = {**r, "source": "endpoint_name"}
    for r in navn_hits:
        merged.setdefault(r["anchor_node_id"], {**r, "source": "anchor_navn"})
    # Only routable anchors (present in the area's link graph) can be a
    # through-destination — drops same-name duplicates that aren't graph nodes.
    anchors = [a for a in merged.values() if a["anchor_node_id"] in routable]
    return {"anchors": anchors[:limit]}


@router.get("/signs/area/{area_code}/distance")
async def through_distance_endpoint(
    area_code: str,
    to_anchor: Annotated[int, Query(description="Destinasjons-ankernode")],
    from_anchor: Annotated[Optional[int], Query(description="Kilde-ankernode (skiltets node)")] = None,
    from_lon: Annotated[Optional[float], Query()] = None,
    from_lat: Annotated[Optional[float], Query()] = None,
):
    """Dijkstra walking distance to a destination anchor over the cross-area
    DNT-route graph, with the per-area correction factor applied. Source is
    `from_anchor` (the signpost's node) or, for point sites without an anchor,
    the nearest anchor to (from_lon, from_lat). Returns distance + the route
    sequence traversed (e.g. ["bre1","bre3"]) so the UI can show "via …".
    Works for proposed signs too — no persisted sign_site_id needed."""
    with op_db_connection() as opc:
        factor = get_distance_correction_factor(opc, area_code)
    with db_connection() as rc:
        from_node = from_anchor if from_anchor is not None else nearest_anchor_node(rc, from_lon, from_lat)
        result = shortest_path_distance(rc, area_code, from_node, to_anchor)
    if result is None:
        return {"found": False, "from_node": from_node, "distance_meters": None, "routes": []}
    raw = result["distance_m"]
    return {
        "found": True,
        "from_node": from_node,
        "raw_meters": raw,
        "correction_factor": factor,
        "distance_meters": raw * factor,
        "routes": result["routes"],
    }


@router.post("/signs/sites/{sign_site_id}/manual-destination")
async def add_manual_destination_endpoint(
    sign_site_id: int,
    anchor_node_id: Annotated[int, Query(description="Destinasjons-ankernode")],
    area: Annotated[str, Query(description="Områdekode, f.eks. 'bre'")],
):
    """Add a named anchor as a manual "through" destination on a sign site. It's
    persisted in ops.sign_site_destinations; the candidates report renders it as
    an extra blade with a Dijkstra distance + route path. Returns the computed
    distance + via for immediate display. 422 if no DNT-route path exists."""
    with op_db_connection() as opc:
        site = get_sign_site_by_id(opc, sign_site_id)
        if not site:
            raise HTTPException(status_code=404, detail=f"Sign site {sign_site_id} not found")
        factor = get_distance_correction_factor(opc, area)
    with db_connection() as rc:
        from_node = site.get("anchor_node_id") or nearest_anchor_node(rc, site.get("lon"), site.get("lat"))
        result = shortest_path_distance(rc, area, from_node, anchor_node_id)
    if result is None:
        raise HTTPException(status_code=422, detail="Fant ingen rute langs DNT-rutene til dette ankerpunktet.")
    with op_db_connection() as opc:
        add_sign_site_destination(opc, sign_site_id, anchor_node_id)
    return {
        "sign_site_id": sign_site_id,
        "anchor_node_id": anchor_node_id,
        "distance_meters": result["distance_m"] * factor,
        "routes": result["routes"],
    }


@router.delete("/signs/sites/{sign_site_id}/manual-destination/{anchor_node_id}", status_code=204)
async def delete_manual_destination_endpoint(sign_site_id: int, anchor_node_id: int):
    """Remove a manual through-destination from a sign site."""
    with op_db_connection() as opc:
        remove_sign_site_destination(opc, sign_site_id, anchor_node_id)
    return Response(status_code=204)


@router.post("/routes/{rutenummer}/signs/sites", response_model=SignSiteResponse, status_code=status.HTTP_201_CREATED)
async def create_sign_site_endpoint(
    rutenummer: str,
    request: SignSiteCreateRequest,
    x_user: Optional[str] = Header(None, alias="X-User"),
):
    """Create a sign site at a point on the route (projected to nearest point on route)."""
    with db_connection() as check_conn:
        routes, _ = get_routes_from_view(check_conn, rutenummer=rutenummer, limit=1, offset=0)
        if not routes:
            raise HTTPException(status_code=404, detail=f"Route '{rutenummer}' not found")

    with db_connection() as conn:
        result = point_on_route_km_and_geom(conn, rutenummer, request.lon, request.lat)
        if not result:
            raise HTTPException(
                status_code=400,
                detail="Could not project point onto route (route has no geometry or point too far)."
            )
        route_km, geom_wkt = result

    updated_by = x_user or "anonymous"
    with op_db_connection() as conn:
        row = create_sign_site(
            conn,
            rutenummer=rutenummer,
            route_km=route_km,
            geom_wkt=geom_wkt,
            anchor_node_id=None,
            name=None,
            back_text=None,
            send_to_name=None,
            send_to_address=None,
            skiltfarge=request.skiltfarge,
            updated_by=updated_by,
        )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create sign site")
    with op_db_connection() as conn:
        full = get_sign_site_by_id(conn, row["id"])
    full = full or row
    return SignSiteResponse(
        id=full["id"],
        rutenummer=full.get("rutenummer"),
        route_km=full.get("route_km"),
        lon=full.get("lon"),
        lat=full.get("lat"),
        anchor_node_id=full.get("anchor_node_id"),
        name=full.get("name"),
        back_text=full.get("back_text"),
        send_to_name=full.get("send_to_name"),
        send_to_address=full.get("send_to_address"),
        skiltfarge=full.get("skiltfarge"),
        created_at=full.get("created_at").isoformat() if full.get("created_at") else None,
        updated_at=full.get("updated_at").isoformat() if full.get("updated_at") else None,
    )


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
                    f.oppdateringsdato,
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
                first_row = fotruteinfo_rows[0] if fotruteinfo_rows else {}
                segment_length = first_row.get('length_meters')
                segment_lokalid = first_row.get('segment_lokalid')
                oppd = first_row.get('oppdateringsdato')
                oppdateringsdato = oppd.isoformat() if oppd is not None and hasattr(oppd, 'isoformat') else (str(oppd) if oppd is not None else None)
                segment_metadata_dump.append({
                    'segment_objid': str(segment_objid),
                    'segment_lokalid': segment_lokalid,
                    'length_meters': float(segment_length) if segment_length is not None else None,
                    'fotruteinfo_count': len(fotruteinfo_rows),
                    'oppdateringsdato': oppdateringsdato,
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

            # Latest oppdateringsdato among segments of this route
            route_last_updated = None
            for fotruteinfo_rows in segments_dict.values():
                for row in fotruteinfo_rows:
                    oppd = row.get('oppdateringsdato')
                    if oppd is not None:
                        oppd_str = oppd.isoformat() if hasattr(oppd, 'isoformat') else str(oppd)
                        if route_last_updated is None or (oppd_str and oppd_str > route_last_updated):
                            route_last_updated = oppd_str

            # Latest oppdateringsdato in turrutebasen (whole fotrute table)
            database_last_updated = None
            try:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        f"SELECT MAX(oppdateringsdato) as database_last_updated FROM {schema_quoted}.fotrute"
                    )
                    row = cur.fetchone()
                    if row and row.get('database_last_updated') is not None:
                        oppd = row['database_last_updated']
                        database_last_updated = oppd.isoformat() if hasattr(oppd, 'isoformat') else str(oppd)
            except Exception:
                pass

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
                    'route_last_updated': route_last_updated,
                    'database_last_updated': database_last_updated,
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

            # First verify segment exists and get oppdateringsdato
            segment_check_query = f"""
                SELECT objid, oppdateringsdato
                FROM {schema_quoted}.fotrute
                WHERE objid = %s
                LIMIT 1
            """
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(segment_check_query, (segment_objid,))
                segment_row = cur.fetchone()

            if not segment_row:
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
                oppd = segment_row.get("oppdateringsdato")
                oppdateringsdato = oppd.isoformat() if oppd is not None and hasattr(oppd, "isoformat") else (str(oppd) if oppd is not None else None)
                return {
                    "segment_objid": segment_objid,
                    "routes": [],
                    "total": 0,
                    "oppdateringsdato": oppdateringsdato,
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

            oppd = segment_row.get("oppdateringsdato")
            oppdateringsdato = oppd.isoformat() if oppd is not None and hasattr(oppd, "isoformat") else (str(oppd) if oppd is not None else None)
            return {
                "segment_objid": segment_objid,
                "routes": routes,
                "total": len(routes),
                "oppdateringsdato": oppdateringsdato,
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