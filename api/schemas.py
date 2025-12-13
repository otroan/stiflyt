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


class EndpointInfo(BaseModel):
    """Information about a route endpoint."""
    name: str
    source: str  # 'ruteinfopunkt' or 'stedsnavn'
    distance_meters: Optional[float] = None
    coordinates: Optional[List[float]] = None  # [lon, lat]


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
    components: Optional[List[List[int]]] = None  # List of component lists (each component is a list of objids)
    report: Optional[Dict[str, Any]] = None  # Route report with component and appendix information
    start_point: Optional[EndpointInfo] = None  # Name and info for start point
    end_point: Optional[EndpointInfo] = None  # Name and info for end point


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


class BboxRouteItem(BaseModel):
    """Route item in bounding box response."""
    rutenummer: str
    rutenavn: Optional[str] = None
    vedlikeholdsansvarlig: Optional[str] = None
    geometry: Dict[str, Any]  # GeoJSON geometry
    segment_count: int
    total_length_meters: float
    total_length_km: float


class BboxRouteResponse(BaseModel):
    """Bounding box route response."""
    routes: List[BboxRouteItem]
    total: int
    bbox: Dict[str, float]  # min_lat, min_lng, max_lat, max_lng


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


class SegmentIssue(BaseModel):
    """Issue found in a segment."""
    type: str
    severity: str  # ERROR, WARNING, INFO
    message: str
    distance_meters: Optional[float] = None
    overlap_length_meters: Optional[float] = None
    segment1_objid: Optional[int] = None
    segment2_objid: Optional[int] = None
    other_segment_objid: Optional[int] = None


class DebugSegment(BaseModel):
    """Segment with debugging information."""
    objid: int
    geometry: Dict[str, Any]
    length_meters: float
    length_km: float
    issues: List[SegmentIssue]


class ConnectionInfo(BaseModel):
    """Connection information between segments."""
    segment1_objid: int
    segment2_objid: int
    distance_meters: float
    end_point: Optional[Dict[str, Any]] = None
    start_point: Optional[Dict[str, Any]] = None
    is_connected: bool


class RouteDebugResponse(BaseModel):
    """Route debugging information response."""
    rutenummer: str
    segments: List[DebugSegment]
    analysis: Dict[str, Any]
    connections: List[ConnectionInfo] = []


class CorrectedSegmentInfo(BaseModel):
    """Segment info in corrected geographic order."""
    objid: int
    geometry: Dict[str, Any]
    length_meters: float
    cumulative_length_meters: float
    component_index: Optional[int] = None  # Index of component this segment belongs to


class ComponentInfo(BaseModel):
    """Information about a route component."""
    index: int
    segment_objids: List[int]
    segment_count: int
    length_meters: float
    is_main: bool


class AppendixInfo(BaseModel):
    """Information about an appendix (disconnected component)."""
    component: List[int]
    segment_objids: List[int]
    segment_count: int
    length_meters: float


class DeadEndSegment(BaseModel):
    """Information about a dead-end segment (utstikker)."""
    segment_objid: int
    length_meters: float
    connected_to: Optional[int] = None  # Which segment it's connected to


class RouteReport(BaseModel):
    """Report about route components and appendices."""
    has_multiple_components: bool
    component_count: int
    is_connected: bool
    components: List[ComponentInfo]
    appendices: List[AppendixInfo] = []
    appendices_count: int = 0
    dead_end_segments: List[DeadEndSegment] = []
    dead_end_count: int = 0


class CorrectedRouteResponse(BaseModel):
    """Corrected geographic route representation."""
    rutenummer: str
    ordered_segment_objids: List  # List of ints if connected, list of lists if disconnected
    geometry: Dict[str, Any]  # GeoJSON geometry
    segments_info: List[CorrectedSegmentInfo]
    total_length_meters: float
    components: List[List[int]] = []  # List of component lists (each component is a list of objids)
    is_connected: bool = True  # True if all segments form a single connected route
    component_count: int = 1  # Number of separate route components
    report: Optional[RouteReport] = None


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


class ExcelReportRequest(BaseModel):
    """Request for Excel report generation."""
    matrikkelenhet_vector: List[MatrikkelenhetItem]
    metadata: Optional[Dict[str, Any]] = None  # Optional metadata (rutenummer, rutenavn, total_length_km, etc.)
    title: Optional[str] = "Rapport"  # Title for the report


class AnchorNodeItem(BaseModel):
    """Anchor node information."""
    node_id: int
    navn: Optional[str] = None
    navn_kilde: Optional[str] = None
    navn_distance_m: Optional[float] = None


class AnchorNodeResponse(BaseModel):
    """Response for anchor node lookup (without geometry)."""
    nodes: List[AnchorNodeItem]
    total: int

