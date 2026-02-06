"""MCP tools wrapping the Stiflyt backend API."""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .client import StiflytClient, _json_result

# Lazy client so env vars are read at first use
_client: Optional[StiflytClient] = None


def _get_client() -> StiflytClient:
    global _client
    if _client is None:
        _client = StiflytClient()
    return _client


def create_app() -> FastMCP:
    """Create and return the FastMCP app with all Stiflyt tools registered."""
    mcp = FastMCP("Stiflyt", json_response=True)

    # --- Search ---
    @mcp.tool()
    def search_places(q: str, limit: int = 20) -> str:
        """Search across places, route points, and routes. q: search string (min 2 chars). limit: max results (1-200)."""
        return _json_result(_get_client().search_places(q, limit=limit))

    # --- Routes ---
    @mcp.tool()
    def list_routes(
        prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        bbox: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_geometry: bool = False,
    ) -> str:
        """List routes with optional filters: prefix, vedlikeholdsansvarlig, bbox (xmin,ymin,xmax,ymax)."""
        return _json_result(
            _get_client().get_routes(
                prefix=prefix,
                vedlikeholdsansvarlig=vedlikeholdsansvarlig,
                bbox=bbox,
                limit=limit,
                offset=offset,
                include_geometry=include_geometry,
            )
        )

    @mcp.tool()
    def get_route(rutenummer: str, include_geometry: bool = False) -> str:
        """Get a single route by rutenummer (e.g. bre10, jot-1)."""
        return _json_result(_get_client().get_route(rutenummer, include_geometry=include_geometry))

    @mcp.tool()
    def get_route_complete(
        rutenummer: str,
        include_geometry: bool = True,
        include_segments: bool = False,
        include_endpoint_names: bool = True,
    ) -> str:
        """Get complete route with merged geometry and endpoint names."""
        return _json_result(
            _get_client().get_route_complete(
                rutenummer,
                include_geometry=include_geometry,
                include_segments=include_segments,
                include_endpoint_names=include_endpoint_names,
            )
        )

    @mcp.tool()
    def get_route_segments(rutenummer: str, include_geometry: bool = False) -> str:
        """Get segments for a specific route."""
        return _json_result(_get_client().get_route_segments(rutenummer, include_geometry=include_geometry))

    @mcp.tool()
    def get_route_links(rutenummer: str, include_geometry: bool = False) -> str:
        """Get routing links for a specific route."""
        return _json_result(_get_client().get_route_links(rutenummer, include_geometry=include_geometry))

    @mcp.tool()
    def validate_route(rutenummer: str) -> str:
        """Validate a route (metadata and geometry consistency)."""
        return _json_result(_get_client().validate_route(rutenummer))

    @mcp.tool()
    def get_routes_statistics(
        prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        bbox: Optional[str] = None,
    ) -> str:
        """Get route statistics (total count, total km, distinct km). At least one filter required."""
        return _json_result(
            _get_client().get_routes_statistics(
                prefix=prefix,
                vedlikeholdsansvarlig=vedlikeholdsansvarlig,
                bbox=bbox,
            )
        )

    @mcp.tool()
    def get_route_areas(
        vedlikeholdsansvarlig: Optional[str] = None,
        debug: bool = False,
        debug_prefix: Optional[str] = None,
    ) -> str:
        """Get unique 3-letter area prefixes from route segments."""
        return _json_result(
            _get_client().get_route_areas(
                vedlikeholdsansvarlig=vedlikeholdsansvarlig,
                debug=debug,
                debug_prefix=debug_prefix,
            )
        )

    @mcp.tool()
    def get_routes_bulk(rutenummer: str, include_geometry: bool = False) -> str:
        """Get multiple routes by comma-separated rutenummer (e.g. bre10,bre11,jot5). Max 100."""
        return _json_result(_get_client().get_routes_bulk(rutenummer, include_geometry=include_geometry))

    # --- Segments ---
    @mcp.tool()
    def list_route_segments(
        rutenummer_prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_geometry: bool = False,
    ) -> str:
        """List route segments filtered by prefix and/or vedlikeholdsansvarlig. At least one filter required."""
        return _json_result(
            _get_client().get_route_segments_list(
                rutenummer_prefix=rutenummer_prefix,
                vedlikeholdsansvarlig=vedlikeholdsansvarlig,
                limit=limit,
                offset=offset,
                include_geometry=include_geometry,
            )
        )

    @mcp.tool()
    def get_segment_routes(segment_objid: int) -> str:
        """Get all route numbers that use a given segment by segment object ID."""
        return _json_result(_get_client().get_segment_routes(segment_objid))

    @mcp.tool()
    def get_segment_by_lokalid(lokalid: str) -> str:
        """Get a segment by its turrutebasen lokalId."""
        return _json_result(_get_client().get_segment_by_lokalid(lokalid))

    # --- Links / anchor-nodes ---
    @mcp.tool()
    def get_links(
        bbox: str,
        limit: int = 500,
        offset: int = 0,
        rutenummer_prefix: Optional[str] = None,
    ) -> str:
        """Get links in bounding box (xmin,ymin,xmax,ymax WGS84). Optional rutenummer_prefix filter."""
        return _json_result(
            _get_client().get_links(
                bbox=bbox,
                limit=limit,
                offset=offset,
                rutenummer_prefix=rutenummer_prefix,
            )
        )

    @mcp.tool()
    def get_anchor_nodes(
        node_ids: Optional[str] = None,
        bbox: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> str:
        """Get anchor nodes. Pass node_ids (comma-separated) or bbox (xmin,ymin,xmax,ymax) or neither for all up to limit."""
        return _json_result(
            _get_client().get_anchor_nodes(
                node_ids=node_ids,
                bbox=bbox,
                limit=limit,
                offset=offset,
            )
        )

    # --- Route anchors ---
    @mcp.tool()
    def get_route_anchors(rutenummer: str) -> str:
        """Get anchor nodes for a route with names and link counts."""
        return _json_result(_get_client().get_route_anchors(rutenummer))

    @mcp.tool()
    def get_anchor_placenames(anchor_id: int) -> str:
        """Get placename candidates and facilities near an anchor node."""
        return _json_result(_get_client().get_anchor_placenames(anchor_id))

    @mcp.tool()
    def upsert_anchor_name(
        anchor_id: int,
        name: str,
        source_type: str,
        source_id: Optional[str] = None,
        distance_meters: Optional[float] = None,
        rutenummer: Optional[str] = None,
    ) -> str:
        """Upsert a validated endpoint name for an anchor node. source_type e.g. ruteinfopunkt, stedsnavn."""
        return _json_result(
            _get_client().upsert_anchor_name(
                anchor_id=anchor_id,
                name=name,
                source_type=source_type,
                source_id=source_id,
                distance_meters=distance_meters,
                rutenummer=rutenummer,
            )
        )

    # --- Signs ---
    @mcp.tool()
    def get_route_signs(rutenummer: str) -> str:
        """Get sign report for a route."""
        return _json_result(_get_client().get_route_signs(rutenummer))

    @mcp.tool()
    def get_signs_by_prefix(prefix: Optional[str] = None) -> str:
        """Get sign report by route prefix."""
        return _json_result(_get_client().get_signs_by_prefix(prefix))

    @mcp.tool()
    def get_signs_missing(prefix: str) -> str:
        """Get missing signs report for a route prefix (prefix required)."""
        return _json_result(_get_client().get_signs_missing(prefix))

    @mcp.tool()
    def get_signs_production(prefix: str) -> str:
        """Get signs production export for a route prefix (prefix required)."""
        return _json_result(_get_client().get_signs_production(prefix))

    @mcp.tool()
    def get_route_signs_production(rutenummer: str) -> str:
        """Get signs production export for a single route."""
        return _json_result(_get_client().get_route_signs_production(rutenummer))

    # --- Geometry / matrikkel ---
    @mcp.tool()
    def get_geometry_owners(geometry: str) -> str:
        """Get property owners for a LineString geometry. geometry: JSON string e.g. {\"type\":\"LineString\",\"coordinates\":[[lon,lat],...]}."""
        try:
            geom = json.loads(geometry)
        except json.JSONDecodeError as e:
            return _json_result({"error": "invalid_json", "detail": str(e)})
        return _json_result(_get_client().get_geometry_owners(geom))

    @mcp.tool()
    def get_point_matrikkelenhet(lat: float, lon: float) -> str:
        """Get matrikkelenhet (parcel) and optional owner info for a point (WGS84 lat, lon)."""
        return _json_result(_get_client().get_point_matrikkelenhet(lat, lon))

    # --- Changesets ---
    @mcp.tool()
    def list_changesets(limit: int = 100, offset: int = 0) -> str:
        """List all changesets (returns array)."""
        return _json_result(_get_client().list_changesets(limit=limit, offset=offset))

    @mcp.tool()
    def create_changeset(
        title: str,
        description: Optional[str] = None,
        area: Optional[str] = None,
        linked_issue_url: Optional[str] = None,
        base_snapshot: str = "default",
    ) -> str:
        """Create a new changeset. Returns the created changeset."""
        return _json_result(
            _get_client().create_changeset(
                title=title,
                description=description,
                area=area,
                linked_issue_url=linked_issue_url,
                base_snapshot=base_snapshot,
            )
        )

    @mcp.tool()
    def get_changeset(changeset_id: str) -> str:
        """Get a changeset by ID."""
        return _json_result(_get_client().get_changeset(changeset_id))

    @mcp.tool()
    def add_changeset_event(changeset_id: str, event: str, x_user: Optional[str] = None) -> str:
        """Add an event to a changeset. event: JSON string of the event object (type, target, patch/geometry/etc)."""
        try:
            ev = json.loads(event)
        except json.JSONDecodeError as e:
            return _json_result({"error": "invalid_json", "detail": str(e)})
        return _json_result(_get_client().add_changeset_event(changeset_id, ev, x_user=x_user))

    @mcp.tool()
    def get_changeset_events(changeset_id: str) -> str:
        """Get all events for a changeset."""
        return _json_result(_get_client().get_changeset_events(changeset_id))

    @mcp.tool()
    def validate_changeset(changeset_id: str) -> str:
        """Validate a changeset."""
        return _json_result(_get_client().validate_changeset(changeset_id))

    @mcp.tool()
    def get_changeset_diff_geojson(changeset_id: str) -> str:
        """Get diff GeoJSON for a changeset."""
        return _json_result(_get_client().get_changeset_diff_geojson(changeset_id))

    @mcp.tool()
    def get_changeset_effective_geojson(changeset_id: str) -> str:
        """Get effective GeoJSON (base + changes) for a changeset."""
        return _json_result(_get_client().get_changeset_effective_geojson(changeset_id))

    @mcp.tool()
    def get_changeset_artifact(changeset_id: str, filename: str) -> str:
        """Download a changeset artifact (filename must end with .json). Returns content or error."""
        return _json_result(_get_client().get_changeset_artifact(changeset_id, filename))

    @mcp.tool()
    def publish_changeset(changeset_id: str, x_user: Optional[str] = None) -> str:
        """Publish a changeset (send to review)."""
        return _json_result(_get_client().publish_changeset(changeset_id, x_user=x_user))

    # --- Editor ---
    @mcp.tool()
    def get_snap_targets(bbox: str) -> str:
        """Get snap targets for a bounding box (min_lon,min_lat,max_lon,max_lat)."""
        return _json_result(_get_client().get_snap_targets(bbox))

    # --- Health ---
    @mcp.tool()
    def health() -> str:
        """Check if the Stiflyt backend is up."""
        return _json_result(_get_client().health())

    return mcp
