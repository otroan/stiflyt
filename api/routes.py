"""API routes."""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from .schemas import RouteResponse, ErrorResponse, RouteSearchResponse, RouteListItem, RouteSegmentsResponse, RouteDebugResponse, CorrectedRouteResponse
from services.route_service import get_route_data, search_routes, get_route_list, get_route_segments_data
from services.route_debug import get_route_debug_info
from services.route_geometry import get_corrected_route_geometry
from services.database import get_db_connection

router = APIRouter()


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
async def get_route(rutenummer: str):
    """
    Get route data by route name (rutenummer).

    Returns:
    - geometry: GeoJSON geometry of the route
    - metadata: Route metadata (name, organization, length, etc.)
    - matrikkelenhet_vector: 1D vector of matrikkelenhet and bruksnavn along the route
    """
    try:
        route_data = get_route_data(rutenummer)

        if route_data is None:
            raise HTTPException(
                status_code=404,
                detail=f"Route '{rutenummer}' not found"
            )

        return RouteResponse(**route_data)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = str(e)
        print(f"Error processing route {rutenummer}: {error_detail}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error processing route '{rutenummer}': {error_detail}"
        )


@router.get("/routes/{rutenummer}/segments", response_model=RouteSegmentsResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_route_segments(rutenummer: str):
    """
    Get individual segments for a route.

    Returns each segment separately with its geometry and length.
    Useful for debugging route data issues like overlapping segments.
    """
    try:
        segments_data = get_route_segments_data(rutenummer)

        if segments_data is None:
            raise HTTPException(
                status_code=404,
                detail=f"Route '{rutenummer}' not found"
            )

        return RouteSegmentsResponse(**segments_data)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = str(e)
        print(f"Error getting segments for route {rutenummer}: {error_detail}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error getting segments for route '{rutenummer}': {error_detail}"
        )


@router.get("/routes/{rutenummer}/debug", response_model=RouteDebugResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_route_debug(rutenummer: str):
    """
    Get debugging information for a route.

    Returns segments with identified issues like:
    - Disconnected segments
    - Overlapping segments
    - Zero-length segments
    - Other data quality issues
    """
    try:
        debug_info = get_route_debug_info(rutenummer)

        if not debug_info['segments']:
            raise HTTPException(
                status_code=404,
                detail=f"Route '{rutenummer}' not found"
            )

        return RouteDebugResponse(**debug_info)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = str(e)
        print(f"Error getting debug info for route {rutenummer}: {error_detail}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error getting debug info for route '{rutenummer}': {error_detail}"
        )


@router.get("/routes/{rutenummer}/corrected", response_model=CorrectedRouteResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_corrected_route(rutenummer: str):
    """
    Get corrected geographic representation of a route.

    This endpoint reconstructs the actual geographic order of route segments
    by following connections between segments, rather than relying on database order.

    Useful when the database order (ORDER BY objid) doesn't match the geographic order.
    """
    try:
        conn = get_db_connection()
        try:
            corrected_data = get_corrected_route_geometry(conn, rutenummer)

            if corrected_data is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Route '{rutenummer}' not found"
                )

            return CorrectedRouteResponse(**corrected_data)
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = str(e)
        print(f"Error getting corrected route for {rutenummer}: {error_detail}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error getting corrected route for '{rutenummer}': {error_detail}"
        )

