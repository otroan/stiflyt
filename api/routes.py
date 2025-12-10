"""API routes."""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from .schemas import RouteResponse, ErrorResponse, RouteSearchResponse, RouteListItem
from services.route_service import get_route_data, search_routes, get_route_list

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

