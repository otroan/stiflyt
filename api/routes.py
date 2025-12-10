"""API routes."""
from fastapi import APIRouter, HTTPException
from .schemas import RouteResponse, ErrorResponse
from services.route_service import get_route_data

router = APIRouter()


@router.get("/routes/{rutenummer}", response_model=RouteResponse, responses={404: {"model": ErrorResponse}})
async def get_route(rutenummer: str):
    """
    Get route data by route name (rutenummer).

    Returns:
    - geometry: GeoJSON geometry of the route
    - metadata: Route metadata (name, organization, length, etc.)
    - matrikkelenhet_vector: 1D vector of matrikkelenhet and bruksnavn along the route
    """
    route_data = get_route_data(rutenummer)

    if route_data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Route '{rutenummer}' not found"
        )

    return RouteResponse(**route_data)

