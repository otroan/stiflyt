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


class PointMatrikkelRequest(BaseModel):
    """Request for point-based matrikkelenhet lookup."""
    lat: float  # Latitude in WGS84 (EPSG:4326)
    lon: float  # Longitude in WGS84 (EPSG:4326)


class PointMatrikkelResponse(BaseModel):
    """Response for point-based matrikkelenhet lookup."""
    matrikkelenhet: str
    matrikkelnummertekst: Optional[str] = None
    bruksnavn: Optional[str] = None
    kommunenummer: Optional[int] = None
    kommunenavn: Optional[str] = None
    arealmerknadtekst: Optional[str] = None
    lagretberegnetareal: Optional[float] = None
    gardsnummer: Optional[int] = None
    bruksnummer: Optional[int] = None
    festenummer: Optional[int] = None
    polygon_geometry: Dict[str, Any]  # GeoJSON Polygon geometry
    owners: Optional[str] = None  # Owner information from Matrikkel API
    owner_error: Optional[str] = None  # Error message if owner lookup failed
    teigid: Optional[int] = None


class RouteInfo(BaseModel):
    """Route information for a segment."""
    rutenummer: str
    rutenavn: Optional[str] = None
    vedlikeholdsansvarlig: Optional[str] = None


class RouteSegment(BaseModel):
    """Route segment information with grouped routes."""
    objid: int
    object_uuid: str
    routes: List[RouteInfo]  # List of routes that use this segment
    length_meters: Optional[float] = None
    geometry: Optional[Dict[str, Any]] = None  # GeoJSON geometry (optional)
    oppdateringsdato: Optional[str] = None  # Last updated in turrutebasen (ISO timestamp)


class RouteSegmentsResponse(BaseModel):
    """Response for route segments query."""
    segments: List[RouteSegment]
    total: int
    limit: int
    offset: int


class EndpointName(BaseModel):
    """Endpoint name information from place name lookup."""
    name: str
    source: str  # 'ruteinfopunkt' | 'stedsnavn' | 'anchor_node'
    distance_meters: Optional[float] = None
    coordinates: Optional[List[float]] = None  # [lon, lat]
    tilrettelegging: Optional[str] = None  # Only present for ruteinfopunkt source
    is_validated: bool = False  # True if name comes from ops.endpoint_names


class PlacenameCandidate(BaseModel):
    """Candidate placename near an anchor."""
    name: str
    source_type: str  # 'ruteinfopunkt' | 'stedsnavn' | 'anchor_node'
    source_id: Optional[str] = None
    distance_meters: Optional[float] = None
    tilrettelegging: Optional[str] = None


class FacilityCandidate(BaseModel):
    """Facility candidate from ruteinfopunkt."""
    name: str
    source_id: Optional[str] = None
    distance_meters: Optional[float] = None
    tilrettelegging: Optional[str] = None


class AnchorFacilitiesResponse(BaseModel):
    """Facilities near an anchor node."""
    anchor_node_id: int
    radius_meters: float
    facilities: List[FacilityCandidate]


class PlacenameCandidatesResponse(BaseModel):
    """Response for placename candidates."""
    anchor_node_id: int
    radius_meters: float
    candidates: List[PlacenameCandidate]
    facilities: List[FacilityCandidate]


class AnchorNodeName(BaseModel):
    """Validated anchor node name with provenance."""
    name: str
    source_type: str
    source_id: Optional[str] = None
    distance_meters: Optional[float] = None
    validated_by: Optional[str] = None
    validated_at: Optional[str] = None


class AnchorNodeInfo(BaseModel):
    """Anchor node info for a route."""
    anchor_node_id: int
    coordinates: List[float]  # [lon, lat]
    link_count: int
    name: Optional[AnchorNodeName] = None


class RouteAnchorsResponse(BaseModel):
    """Response for route anchor nodes."""
    rutenummer: str
    anchors: List[AnchorNodeInfo]
    total: int


class SignDestination(BaseModel):
    """Destination entry for a sign report."""
    anchor_node_id: int
    name: str
    distance_meters: float


class SignStatus(BaseModel):
    """Operational sign status metadata."""
    direction: Optional[str] = None
    status: Optional[str] = None
    last_inspected: Optional[str] = None
    notes: Optional[str] = None
    front_lon: Optional[float] = None
    front_lat: Optional[float] = None
    back_lon: Optional[float] = None
    back_lat: Optional[float] = None
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None


class SignReportItem(BaseModel):
    """Computed sign report item."""
    anchor_node_id: int
    coordinates: Optional[List[float]] = None  # [lon, lat]
    link_count: int
    is_endpoint: bool
    is_junction: bool
    name: Optional[str] = None
    destinations: List[SignDestination]
    status: List[SignStatus] = []


class SignsMissingItem(BaseModel):
    """Missing sign item."""
    anchor_node_id: int
    coordinates: Optional[List[float]] = None
    reason: str


class SignsMissingReport(BaseModel):
    """Missing signs report."""
    missing_signs: List[SignsMissingItem]
    missing_destinations: List[SignsMissingItem]
    missing_anchor_names: List[SignsMissingItem]


class SignsReportResponse(BaseModel):
    """Signs report response."""
    scope: Dict[str, Any]
    signs: List[SignReportItem]
    missing: SignsMissingReport
    totals: Dict[str, Any]


class SignsProductionResponse(BaseModel):
    """Signs production export response."""
    scope: Dict[str, Any]
    rows: List[Dict[str, Any]]


class AnchorNameUpsertRequest(BaseModel):
    """Request to upsert a validated anchor name."""
    name: str
    source_type: str
    source_id: Optional[str] = None
    distance_meters: Optional[float] = None
    rutenummer: Optional[str] = None


class AnchorNameUpsertResponse(BaseModel):
    """Response for anchor name upsert."""
    anchor_node_id: int
    rutenummer: Optional[str] = None
    name: str
    source_type: str
    source_id: Optional[str] = None
    distance_meters: Optional[float] = None
    validated_by: Optional[str] = None
    validated_at: Optional[str] = None


class RouteComponent(BaseModel):
    """Route component information (for disconnected routes)."""
    index: int
    segment_objids: List[int]
    segment_count: int
    length_meters: float
    is_main: bool


class CompleteRouteResponse(BaseModel):
    """Response for complete route with combined segments and endpoint names."""
    rutenummer: str
    rutenavn: Optional[str] = None
    vedlikeholdsansvarlig: Optional[str] = None
    geometry: Optional[Dict[str, Any]] = None  # GeoJSON LineString/MultiLineString
    total_length_meters: float
    total_length_km: float
    from_name: Optional[EndpointName] = None
    to_name: Optional[EndpointName] = None
    is_connected: bool
    segment_count: int
    component_count: int
    segments: Optional[List[RouteSegment]] = None  # Only included if include_segments=true
    components: Optional[List[RouteComponent]] = None  # Only included if multiple components


class Route(BaseModel):
    """Route from stiflyt.routes materialized view."""
    rutenummer: str
    rutenavn: Optional[str] = None
    vedlikeholdsansvarlig: Optional[str] = None
    rutetype: Optional[str] = None
    route_geometry: Optional[Dict[str, Any]] = None  # GeoJSON geometry (optional)
    total_length_m: float
    segment_count: int
    segment_objids: Optional[List[int]] = None
    from_name: Optional[str] = None  # Start endpoint name from anchor_nodes
    to_name: Optional[str] = None  # End endpoint name from anchor_nodes


class RoutesResponse(BaseModel):
    """Response for routes query."""
    routes: List[Route]
    total: int
    limit: int
    offset: int


class RoutesStatisticsResponse(BaseModel):
    """Response for routes statistics (total km and distinct km)."""
    total_routes: int
    total_km: float
    distinct_km: float


class RouteSegmentDetail(BaseModel):
    """Route segment detail from stiflyt.route_segments view."""
    rutenummer: str
    segment_objid: int
    object_uuid: str
    senterlinje: Optional[Dict[str, Any]] = None  # GeoJSON geometry
    source_node: Optional[int] = None
    target_node: Optional[int] = None
    rutenavn: Optional[str] = None
    vedlikeholdsansvarlig: Optional[str] = None
    rutetype: Optional[str] = None
    gradering: Optional[str] = None
    length_meters: Optional[float] = None
    oppdateringsdato: Optional[str] = None  # Last updated in turrutebasen (ISO timestamp)


class RouteSegmentsDetailResponse(BaseModel):
    """Response for route segments detail query."""
    rutenummer: str
    segments: List[RouteSegmentDetail]
    total: int


class RouteLink(BaseModel):
    """Route link from stiflyt.links_with_routes table (routing topology)."""
    link_id: int
    a_node: Optional[int] = None
    b_node: Optional[int] = None
    a_node_name: Optional[str] = None  # Name of a_node from anchor_nodes
    b_node_name: Optional[str] = None  # Name of b_node from anchor_nodes
    length_m: Optional[float] = None
    segment_objids: Optional[List[int]] = None
    geom: Optional[Dict[str, Any]] = None  # GeoJSON geometry


class RouteLinksResponse(BaseModel):
    """Response for route links query."""
    rutenummer: str
    links: List[RouteLink]
    total: int


# Validation schemas
class ValidationIssue(BaseModel):
    """A single validation issue."""
    type: str
    message: str
    severity: str  # 'error' | 'warning' | 'info'
    affected_segments: Optional[List[str]] = None
    affected_links: Optional[List[int]] = None
    metadata: Optional[Dict[str, Any]] = None


class SegmentMetadata(BaseModel):
    """Metadata for a route segment."""
    segment_objid: str
    segment_lokalid: Optional[str] = None
    length_meters: Optional[float] = None
    fotruteinfo_count: int
    fotruteinfo_rows: List[Dict[str, Any]]
    oppdateringsdato: Optional[str] = None  # Last updated in turrutebasen (ISO timestamp)


class ValidationSummary(BaseModel):
    """Summary of validation results."""
    total_segments: int
    total_fotruteinfo_rows: int
    total_links: int
    error_count: int
    warning_count: int
    geometry_error_count: int
    geometry_warning_count: int
    rutenavn_values: Optional[List[str]] = None
    vedlikeholdsansvarlig_values: Optional[List[str]] = None
    rutetype_values: Optional[List[str]] = None
    gradering_values: Optional[List[str]] = None


class RouteValidationResponse(BaseModel):
    """Response for route validation."""
    rutenummer: str
    segment_count: int
    link_count: int
    status: str  # 'OK' | 'WARNING' | 'ERROR'
    errors: List[ValidationIssue]
    warnings: List[ValidationIssue]
    geometry_info: List[ValidationIssue]
    segment_metadata: List[SegmentMetadata]
    summary: ValidationSummary


class SegmentByLokalIdResponse(BaseModel):
    """Response for segment lookup by lokalid."""
    segment: Dict[str, Any]
    fotruteinfo_rows: List[Dict[str, Any]]


class RouteAreasResponse(BaseModel):
    """Response for route area prefixes."""
    areas: List[str]
    total: int
    vedlikeholdsansvarlig: Optional[str] = None
    debug: Optional[Dict[str, Any]] = None


