"""Pydantic schemas for API request/response."""
from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class MatrikkelenhetItem(BaseModel):
    """Matrikkelenhet item in the vector."""
    matrikkelenhet: str
    bruksnavn: Optional[str] = None
    kommunenummer: Optional[str] = None
    kommunenavn: Optional[str] = None
    offset_meters: float
    offset_km: float
    length_meters: float
    length_km: float


class RouteMetadata(BaseModel):
    """Route metadata."""
    rutenummer: str
    rutenavn: str
    vedlikeholdsansvarlig: Optional[str] = None
    total_length_meters: float
    total_length_km: float
    segment_count: int


class RouteResponse(BaseModel):
    """Route API response."""
    geometry: Dict[str, Any]  # GeoJSON geometry
    metadata: RouteMetadata
    matrikkelenhet_vector: List[MatrikkelenhetItem]


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None


class RouteListItem(BaseModel):
    """Route list item for search results."""
    rutenummer: str
    rutenavn: str
    vedlikeholdsansvarlig: Optional[str] = None
    segment_count: int


class RouteSearchResponse(BaseModel):
    """Route search response."""
    routes: List[RouteListItem]
    total: int


class RouteSegment(BaseModel):
    """Individual route segment."""
    objid: int
    geometry: Dict[str, Any]  # GeoJSON geometry
    length_meters: float
    length_km: float


class RouteSegmentsResponse(BaseModel):
    """Route segments response."""
    rutenummer: str
    rutenavn: str
    segments: List[RouteSegment]
    total_segments: int

