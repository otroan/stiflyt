"""API routes."""
import traceback
from functools import wraps
from fastapi import APIRouter, HTTPException, Query, Path
from typing import Optional, Callable, Any
from .schemas import RouteResponse, ErrorResponse, RouteSearchResponse, RouteListItem, RouteSegmentsResponse, RouteDebugResponse, CorrectedRouteResponse
from services.route_service import get_route_data, search_routes, get_route_list, get_route_segments_data, RouteNotFoundError, RouteDataError
from services.route_debug import get_route_debug_info
from services.route_geometry import get_corrected_route_geometry
from services.database import get_db_connection

router = APIRouter()


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

