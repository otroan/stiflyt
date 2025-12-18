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
    geometry: Dict[str, Any]  # GeoJSON geometry of the intersection segment


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None


class PlaceSearchResult(BaseModel):
    """Generic place/route search result with coordinates for map zoom."""
    id: str
    type: str  # ruteinfopunkt | stedsnavn | rute
    title: str
    subtitle: Optional[str] = None
    lon: float
    lat: float
    rutenummer: Optional[str] = None


class PlaceSearchResponse(BaseModel):
    """Response for place search."""
    results: List[PlaceSearchResult]
    total: int


class MatrikkelenhetItemWithOwners(MatrikkelenhetItem):
    """Matrikkelenhet item with owner information."""
    owners: Optional[str] = None  # Owner information from Matrikkel API


class GeometryOwnerRequest(BaseModel):
    """Request for geometry owner lookup."""
    geometry: Dict[str, Any]  # GeoJSON LineString geometry


class GeometryOwnerResponse(BaseModel):
    """Response for geometry owner lookup."""
    geometry: Dict[str, Any]  # GeoJSON LineString geometry
    total_length_meters: float
    total_length_km: float
    matrikkelenhet_vector: List[MatrikkelenhetItemWithOwners]
    error_summary: Optional[str] = None  # Summary of errors when fetching owner information


class ExcelReportRequest(BaseModel):
    """Request for Excel report generation."""
    matrikkelenhet_vector: List[MatrikkelenhetItem]
    metadata: Optional[Dict[str, Any]] = None  # Optional metadata (rutenummer, rutenavn, total_length_km, etc.)
    title: Optional[str] = "Rapport"  # Title for the report

