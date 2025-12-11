"""API routes."""
import secrets
import traceback
from functools import wraps
from typing import Optional, Callable, Any

from fastapi import APIRouter, HTTPException, Query, Path, Depends, Response, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from .schemas import RouteResponse, ErrorResponse, RouteSearchResponse, RouteListItem, RouteSegmentsResponse, RouteDebugResponse, CorrectedRouteResponse, BboxRouteResponse, BboxRouteItem
from services.route_service import get_route_data, search_routes, get_route_list, get_route_segments_data, get_routes_in_bbox, RouteNotFoundError, RouteDataError
from services.route_debug import get_route_debug_info
from services.route_geometry import get_corrected_route_geometry
from services.database import get_db_connection
from services.excel_report import generate_owners_excel

router = APIRouter()
security = HTTPBasic()


def handle_route_errors(operation_name: str):
    """
    Decorator to handle common error patterns for route endpoints.

    Handles:
    - 404 errors when route data is None or empty
    - 500 errors for unexpected exceptions with logging

    Args:
        operation_name: Name of the operation for error messages (e.g., "processing route")
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                # Call the function (it's async but calls sync code, so await it)
                result = await func(*args, **kwargs)

                # Check for None or empty results (common 404 case)
                if result is None:
                    # Extract rutenummer from kwargs or args if available
                    rutenummer = kwargs.get('rutenummer') or (args[0] if args else 'unknown')
                    raise HTTPException(
                        status_code=404,
                        detail=f"Route '{rutenummer}' not found"
                    )

                # Check for empty segments list (specific to debug endpoint)
                if isinstance(result, dict) and 'segments' in result and not result.get('segments'):
                    rutenummer = kwargs.get('rutenummer') or (args[0] if args else 'unknown')
                    raise HTTPException(
                        status_code=404,
                        detail=f"Route '{rutenummer}' not found"
                    )

                return result
            except HTTPException:
                # Re-raise HTTP exceptions (like 404) as-is
                raise
            except RouteNotFoundError as e:
                # Convert RouteNotFoundError to 404 HTTPException
                raise HTTPException(
                    status_code=404,
                    detail=str(e)
                )
            except RouteDataError as e:
                # Convert RouteDataError to 500 HTTPException
                rutenummer = kwargs.get('rutenummer') or (args[0] if args else 'unknown')
                print(f"Route data error for '{rutenummer}': {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=str(e)
                )
            except Exception as e:
                # Handle unexpected errors with logging
                error_detail = str(e)
                rutenummer = kwargs.get('rutenummer') or (args[0] if args else 'unknown')
                print(f"Error {operation_name} '{rutenummer}': {error_detail}")
                print(traceback.format_exc())
                raise HTTPException(
                    status_code=500,
                    detail=f"Error {operation_name} '{rutenummer}': {error_detail}"
                )
        return wrapper
    return decorator


@router.get("/routes", response_model=RouteSearchResponse)
async def search_routes_endpoint(
    prefix: Optional[str] = Query(None, description="Search routes by rutenummer prefix (e.g., 'bre')"),
    name: Optional[str] = Query(None, description="Search routes by name (partial match)"),
    organization: Optional[str] = Query(None, description="Search routes by organization (vedlikeholdsansvarlig)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")
):
    """
    Search for routes by various criteria.

    Examples:
    - /api/v1/routes?prefix=bre - Find all routes starting with "bre"
    - /api/v1/routes?name=skjåk - Find routes with "skjåk" in the name
    - /api/v1/routes?organization=DNT - Find routes maintained by DNT
    - /api/v1/routes - List all routes (up to limit)
    """
    routes = search_routes(
        rutenummer_prefix=prefix,
        rutenavn_search=name,
        organization=organization,
        limit=limit
    )

    route_items = [
        RouteListItem(
            rutenummer=r['rutenummer'],
            rutenavn=r['rutenavn'],
            vedlikeholdsansvarlig=r.get('vedlikeholdsansvarlig'),
            segment_count=r['segment_count']
        )
        for r in routes
    ]

    return RouteSearchResponse(
        routes=route_items,
        total=len(route_items)
    )


@router.get("/routes/bbox", response_model=BboxRouteResponse)
async def get_routes_in_bbox_endpoint(
    min_lat: float = Query(..., description="Minimum latitude (south boundary)", ge=-90, le=90),
    min_lng: float = Query(..., description="Minimum longitude (west boundary)", ge=-180, le=180),
    max_lat: float = Query(..., description="Maximum latitude (north boundary)", ge=-90, le=90),
    max_lng: float = Query(..., description="Maximum longitude (east boundary)", ge=-180, le=180),
    prefix: Optional[str] = Query(None, description="Filter routes by rutenummer prefix (e.g., 'bre')"),
    organization: Optional[str] = Query(None, description="Filter routes by organization (e.g., 'DNT')"),
    limit: int = Query(1000, ge=1, le=1000, description="Maximum number of results"),
    zoom: Optional[int] = Query(None, description="Map zoom level for adaptive geometry simplification (higher zoom = more detail)")
):
    """
    Get routes that intersect with a bounding box.

    Returns routes with simplified geometry where ANY part of the route intersects
    the specified bounding box (not just routes fully contained within the box).
    This includes routes that are partially in the box, touch the boundary, or are
    fully contained. Useful for displaying all routes visible in the current map view.

    Examples:
    - /api/v1/routes/bbox?min_lat=59.0&min_lng=10.0&max_lat=60.0&max_lng=11.0
    - /api/v1/routes/bbox?min_lat=59.0&min_lng=10.0&max_lat=60.0&max_lng=11.0&prefix=bre
    - /api/v1/routes/bbox?min_lat=59.0&min_lng=10.0&max_lat=60.0&max_lng=11.0&organization=DNT
    """
    try:
        routes = get_routes_in_bbox(
            min_lat=min_lat,
            min_lng=min_lng,
            max_lat=max_lat,
            max_lng=max_lng,
            rutenummer_prefix=prefix,
            organization=organization,
            limit=limit,
            zoom_level=zoom
        )

        route_items = [
            BboxRouteItem(
                rutenummer=r['rutenummer'],
                rutenavn=r.get('rutenavn'),  # Handle None values
                vedlikeholdsansvarlig=r.get('vedlikeholdsansvarlig'),
                geometry=r['geometry'],
                segment_count=r['segment_count'],
                total_length_meters=r.get('total_length_meters', 0.0),
                total_length_km=r.get('total_length_km', 0.0)
            )
            for r in routes
            if r.get('geometry')  # Only include routes with valid geometry
        ]

        return BboxRouteResponse(
            routes=route_items,
            total=len(route_items),
            bbox={
                'min_lat': min_lat,
                'min_lng': min_lng,
                'max_lat': max_lat,
                'max_lng': max_lng
            }
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        print(f"Error getting routes in bounding box: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error getting routes in bounding box: {str(e)}"
        )


@router.get("/routes/{rutenummer}", response_model=RouteResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
@handle_route_errors("processing route")
async def get_route(
    rutenummer: str = Path(..., min_length=1, description="Route identifier (rutenummer)")
):
    """
    Get route data by route name (rutenummer).

    Returns:
    - geometry: GeoJSON geometry of the route
    - metadata: Route metadata (name, organization, length, etc.)
    - matrikkelenhet_vector: 1D vector of matrikkelenhet and bruksnavn along the route
    """
    route_data = get_route_data(rutenummer)
    return RouteResponse(**route_data)


@router.get("/routes/{rutenummer}/segments", response_model=RouteSegmentsResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
@handle_route_errors("getting segments for route")
async def get_route_segments(
    rutenummer: str = Path(..., min_length=1, description="Route identifier (rutenummer)")
):
    """
    Get individual segments for a route.

    Returns each segment separately with its geometry and length.
    Useful for debugging route data issues like overlapping segments.
    """
    segments_data = get_route_segments_data(rutenummer)
    return RouteSegmentsResponse(**segments_data)


@router.get("/routes/{rutenummer}/debug", response_model=RouteDebugResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
@handle_route_errors("getting debug info for route")
async def get_route_debug(
    rutenummer: str = Path(..., min_length=1, description="Route identifier (rutenummer)")
):
    """
    Get debugging information for a route.

    Returns segments with identified issues like:
    - Disconnected segments
    - Overlapping segments
    - Zero-length segments
    - Other data quality issues
    """
    debug_info = get_route_debug_info(rutenummer)
    return RouteDebugResponse(**debug_info)


@router.get("/routes/{rutenummer}/corrected", response_model=CorrectedRouteResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
@handle_route_errors("getting corrected route for")
async def get_corrected_route(
    rutenummer: str = Path(..., min_length=1, description="Route identifier (rutenummer)")
):
    """
    Get corrected geographic representation of a route.

    This endpoint reconstructs the actual geographic order of route segments
    by following connections between segments, rather than relying on database order.

    Useful when the database order (ORDER BY objid) doesn't match the geographic order.
    """
    conn = get_db_connection()
    try:
        corrected_data = get_corrected_route_geometry(conn, rutenummer)
        return CorrectedRouteResponse(**corrected_data)
    finally:
        conn.close()

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

@router.get("/routes/{rutenummer}/owners.xlsx")
@handle_route_errors("generating owners Excel report for route")
async def download_route_owners_excel(
    rutenummer: str = Path(..., min_length=1, description="Route identifier (rutenummer)"),
    user=Depends(require_shared_login),
):
    """
    Download Excel report with route owners information.

    Requires authentication. The report contains:
    - Offset along the path (meters and kilometers)
    - Length of path within each matrikkelenhet (meters and kilometers)
    - Matrikkelenhet
    - Bruksnavn
    - Placeholder for kontaktinformasjon (to be filled in phase 2)
    """
    # Generate Excel file using the service
    excel_bytes = generate_owners_excel(rutenummer)

    headers = {
        "Content-Disposition": f'attachment; filename="route-{rutenummer}-owners.xlsx"'
    }
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )