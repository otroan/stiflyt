"""MCP tools wrapping the Stiflyt backend API.

Each @mcp.tool() is a thin shim over StiflytClient. Tool naming follows
the backend's path semantics, not the legacy frontend method names, so an
LLM with no prior context can read the names and call them correctly.
"""
import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .client import StiflytClient, _json_result

_client: Optional[StiflytClient] = None


def _get_client() -> StiflytClient:
    global _client
    if _client is None:
        _client = StiflytClient()
    return _client


def _parse_list(s: Optional[str]) -> Optional[list]:
    """Comma- or JSON-list -> python list. None passthrough."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            v = json.loads(s)
            return v if isinstance(v, list) else [v]
        except json.JSONDecodeError:
            pass
    return [x.strip() for x in s.split(",") if x.strip()]


def create_app() -> FastMCP:
    """Create and return the FastMCP app with all Stiflyt tools registered."""
    mcp = FastMCP("Stiflyt", json_response=True)
    c = _get_client  # local alias

    # =====================================================================
    # Session / health
    # =====================================================================

    @mcp.tool()
    def health() -> str:
        """Check if the Stiflyt backend is up."""
        return _json_result(c().health())

    @mcp.tool()
    def get_me() -> str:
        """Return the authenticated session user, or 401 detail if none."""
        return _json_result(c().get_me())

    # =====================================================================
    # Search
    # =====================================================================

    @mcp.tool()
    def search_places(q: str, limit: int = 20) -> str:
        """Search across places, route points, and routes. q: min 2 chars. limit: 1-200."""
        return _json_result(c().search_places(q, limit=limit))

    # =====================================================================
    # Routes
    # =====================================================================

    @mcp.tool()
    def list_routes(
        prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        bbox: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_geometry: bool = False,
    ) -> str:
        """List routes with optional filters: prefix (e.g. 'bre'), vedlikeholdsansvarlig, bbox (xmin,ymin,xmax,ymax)."""
        return _json_result(
            c().get_routes(
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
        return _json_result(c().get_route(rutenummer, include_geometry=include_geometry))

    @mcp.tool()
    def get_route_complete(
        rutenummer: str,
        include_geometry: bool = True,
        include_segments: bool = False,
        include_endpoint_names: bool = True,
    ) -> str:
        """Get complete route with merged geometry and endpoint names."""
        return _json_result(
            c().get_route_complete(
                rutenummer,
                include_geometry=include_geometry,
                include_segments=include_segments,
                include_endpoint_names=include_endpoint_names,
            )
        )

    @mcp.tool()
    def get_route_segments(rutenummer: str, include_geometry: bool = False) -> str:
        """Get segments for a specific route."""
        return _json_result(c().get_route_segments(rutenummer, include_geometry=include_geometry))

    @mcp.tool()
    def get_route_links(rutenummer: str, include_geometry: bool = False) -> str:
        """Get routing links for a specific route."""
        return _json_result(c().get_route_links(rutenummer, include_geometry=include_geometry))

    @mcp.tool()
    def validate_route(rutenummer: str) -> str:
        """Legacy route validation (metadata + geometry consistency, no area)."""
        return _json_result(c().validate_route(rutenummer))

    @mcp.tool()
    def get_routes_statistics(
        prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        bbox: Optional[str] = None,
    ) -> str:
        """Route statistics (total count, total km, distinct km). At least one filter required."""
        return _json_result(
            c().get_routes_statistics(
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
            c().get_route_areas(
                vedlikeholdsansvarlig=vedlikeholdsansvarlig,
                debug=debug,
                debug_prefix=debug_prefix,
            )
        )

    @mcp.tool()
    def get_routes_bulk(rutenummer: str, include_geometry: bool = False) -> str:
        """Get multiple routes by comma-separated rutenummer (e.g. bre10,bre11,jot5). Max 100."""
        return _json_result(c().get_routes_bulk(rutenummer, include_geometry=include_geometry))

    # =====================================================================
    # Segments
    # =====================================================================

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
            c().get_route_segments_list(
                rutenummer_prefix=rutenummer_prefix,
                vedlikeholdsansvarlig=vedlikeholdsansvarlig,
                limit=limit,
                offset=offset,
                include_geometry=include_geometry,
            )
        )

    @mcp.tool()
    def get_segment_routes(segment_objid: int) -> str:
        """Get all rutenummer that share a segment, by segment object ID."""
        return _json_result(c().get_segment_routes(segment_objid))

    @mcp.tool()
    def get_segment_by_lokalid(lokalid: str) -> str:
        """Get a segment by its turrutebasen lokalId."""
        return _json_result(c().get_segment_by_lokalid(lokalid))

    # =====================================================================
    # Links / anchor nodes
    # =====================================================================

    @mcp.tool()
    def get_links(
        bbox: str,
        limit: int = 500,
        offset: int = 0,
        rutenummer_prefix: Optional[str] = None,
    ) -> str:
        """Get links in bounding box (xmin,ymin,xmax,ymax WGS84). Optional rutenummer_prefix."""
        return _json_result(
            c().get_links(
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
        """Get anchor nodes. node_ids (comma-separated) or bbox; both optional."""
        return _json_result(
            c().get_anchor_nodes(
                node_ids=node_ids,
                bbox=bbox,
                limit=limit,
                offset=offset,
            )
        )

    # =====================================================================
    # Route anchors
    # =====================================================================

    @mcp.tool()
    def get_route_anchors(rutenummer: str) -> str:
        """Anchor nodes for a route with names and link counts."""
        return _json_result(c().get_route_anchors(rutenummer))

    @mcp.tool()
    def get_anchor_placenames(anchor_id: int, radius: int = 500, limit: int = 12) -> str:
        """Placename candidates and facilities near an anchor node."""
        return _json_result(c().get_anchor_placenames(anchor_id, radius=radius, limit=limit))

    @mcp.tool()
    def upsert_anchor_name(
        anchor_id: int,
        name: str,
        source_type: str,
        source_id: Optional[str] = None,
        distance_meters: Optional[float] = None,
        rutenummer: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Upsert a validated endpoint name (legacy endpoint /anchors/{id}/name). source_type e.g. ruteinfopunkt, stedsnavn."""
        return _json_result(
            c().upsert_anchor_name(
                anchor_id=anchor_id,
                name=name,
                source_type=source_type,
                source_id=source_id,
                distance_meters=distance_meters,
                rutenummer=rutenummer,
                x_user=x_user,
            )
        )

    # =====================================================================
    # Signs — legacy reports
    # =====================================================================

    @mcp.tool()
    def get_route_signs(rutenummer: str) -> str:
        """Sign report for a route."""
        return _json_result(c().get_route_signs(rutenummer))

    @mcp.tool()
    def get_signs_by_prefix(prefix: Optional[str] = None) -> str:
        """Sign report by route prefix."""
        return _json_result(c().get_signs_by_prefix(prefix))

    @mcp.tool()
    def get_signs_missing(prefix: str) -> str:
        """Missing signs report for a route prefix."""
        return _json_result(c().get_signs_missing(prefix))

    @mcp.tool()
    def get_signs_production(prefix: str) -> str:
        """Signs production export for a route prefix."""
        return _json_result(c().get_signs_production(prefix))

    @mcp.tool()
    def get_route_signs_production(rutenummer: str) -> str:
        """Signs production export for one route."""
        return _json_result(c().get_route_signs_production(rutenummer))

    # =====================================================================
    # Signs — signs_app candidate / area workflow
    # =====================================================================

    @mcp.tool()
    def get_signs_candidates(area: str) -> str:
        """List candidate sign sites for an area (anchors awaiting accept/reject + already-accepted sites)."""
        return _json_result(c().get_signs_candidates(area))

    @mcp.tool()
    def get_signs_area_routes(area: str) -> str:
        """Per-route summary for an area (with patched geometries for the map)."""
        return _json_result(c().get_signs_area_routes(area))

    @mcp.tool()
    def get_signs_area_stats(area: str) -> str:
        """Aggregate sign stats for an area."""
        return _json_result(c().get_signs_area_stats(area))

    @mcp.tool()
    def get_signs_area_validation(area: str, refresh: bool = False) -> str:
        """Area-level validation report (all routes, all issues). refresh=true forces a recompute."""
        return _json_result(c().get_signs_area_validation(area, refresh=refresh))

    @mcp.tool()
    def accept_sign_candidate(area: str, anchor_node_id: int, x_user: Optional[str] = None) -> str:
        """Accept a candidate anchor as a sign site for an area."""
        return _json_result(c().accept_sign_candidate(area, anchor_node_id, x_user=x_user))

    @mcp.tool()
    def reject_sign_candidate(area: str, anchor_node_id: int, x_user: Optional[str] = None) -> str:
        """Reject a candidate anchor for an area (hides it from the candidate list)."""
        return _json_result(c().reject_sign_candidate(area, anchor_node_id, x_user=x_user))

    @mcp.tool()
    def create_manual_sign(
        area: str,
        rutenummer_list: str,
        lon: float,
        lat: float,
        name: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Create a manual sign site at (lon, lat). rutenummer_list: comma-separated or JSON array (e.g. 'bre21,bre62')."""
        rl = _parse_list(rutenummer_list) or []
        return _json_result(
            c().create_manual_sign(
                area=area,
                rutenummer_list=rl,
                lon=lon,
                lat=lat,
                name=name,
                x_user=x_user,
            )
        )

    @mcp.tool()
    def get_signs_placenames(lon: float, lat: float, radius: int = 500, limit: int = 12) -> str:
        """Placename candidates near a (lon, lat) point — used to label a manual sign site."""
        return _json_result(c().get_signs_placenames(lon=lon, lat=lat, radius=radius, limit=limit))

    @mcp.tool()
    def upsert_signs_anchor_name(anchor_id: int, name: str, x_user: Optional[str] = None) -> str:
        """Set the display name for an anchor (signs_app variant — simple {name} payload)."""
        return _json_result(c().upsert_signs_anchor_name(anchor_id=anchor_id, name=name, x_user=x_user))

    @mcp.tool()
    def update_sign_site_name(sign_site_id: int, name: str, x_user: Optional[str] = None) -> str:
        """Rename a sign site."""
        return _json_result(c().update_sign_site_name(sign_site_id, name, x_user=x_user))

    @mcp.tool()
    def update_sign_site_status(sign_site_id: int, status: str, x_user: Optional[str] = None) -> str:
        """Patch the production status of a sign site (e.g. 'production', 'review', 'done')."""
        return _json_result(c().update_sign_site_status(sign_site_id, status, x_user=x_user))

    @mcp.tool()
    def delete_sign_site(sign_site_id: int, x_user: Optional[str] = None) -> str:
        """Delete a sign site."""
        return _json_result(c().delete_sign_site(sign_site_id, x_user=x_user))

    @mcp.tool()
    def patch_sign_panel(
        sign_site_id: int,
        destination_anchor_node_id: int,
        color: Optional[str] = None,
        direction: Optional[str] = None,
        distance_km: Optional[float] = None,
        destination_name: Optional[str] = None,
        first_link_id: Optional[int] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Edit one panel on a sign site. color: 'trehvit' or 'grønn'. Only provided fields are written.

        first_link_id discriminates panels that share (sign_site_id, anchor_node_id) but
        are parallel-path siblings; always include it when patching.
        """
        return _json_result(
            c().patch_sign_panel(
                sign_site_id=sign_site_id,
                destination_anchor_node_id=destination_anchor_node_id,
                color=color,
                direction=direction,
                distance_km=distance_km,
                destination_name=destination_name,
                first_link_id=first_link_id,
                x_user=x_user,
            )
        )

    @mcp.tool()
    def get_sign_site_destinations(sign_site_id: int) -> str:
        """List all destinations (panels) attached to a sign site."""
        return _json_result(c().get_sign_site_destinations(sign_site_id))

    @mcp.tool()
    def set_sign_site_destinations(
        sign_site_id: int,
        destinations: str,
        x_user: Optional[str] = None,
    ) -> str:
        """Replace the destination set on a sign site. destinations: JSON array of destination objects."""
        try:
            arr = json.loads(destinations)
        except json.JSONDecodeError as e:
            return _json_result({"error": "invalid_json", "detail": str(e)})
        if not isinstance(arr, list):
            return _json_result({"error": "invalid_payload", "detail": "destinations must be a JSON array"})
        return _json_result(c().set_sign_site_destinations(sign_site_id, arr, x_user=x_user))

    @mcp.tool()
    def patch_sign_destination_skilt(
        sign_site_id: int,
        anchor_node_id: int,
        payload: str,
        x_user: Optional[str] = None,
    ) -> str:
        """Patch the 'skilt' (physical sign) attributes for a destination on a site. payload: JSON object."""
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError as e:
            return _json_result({"error": "invalid_json", "detail": str(e)})
        return _json_result(
            c().patch_sign_destination_skilt(sign_site_id, anchor_node_id, obj, x_user=x_user)
        )

    # --- exports (write to artifacts_dir, return path) --------------------

    @mcp.tool()
    def download_signs_manufacturing_xlsx(area: str, panels: Optional[str] = None) -> str:
        """Manufacturing xlsx for an area. panels: optional comma-separated panel ids to filter.

        Writes to STIFLYT_MCP_ARTIFACTS_DIR (default /tmp/stiflyt-mcp) and returns
        {path, size, content_type, filename}. When the MCP server runs on a remote
        host, scp the file from there.
        """
        panel_list = _parse_list(panels) if panels else None
        return _json_result(c().download_signs_manufacturing_xlsx(area, panels=panel_list))

    @mcp.tool()
    def download_signs_field_pdf(area: str, panels: Optional[str] = None) -> str:
        """Field-PDF for an area. panels: optional comma-separated panel ids to filter."""
        panel_list = _parse_list(panels) if panels else None
        return _json_result(c().download_signs_field_pdf(area, panels=panel_list))

    @mcp.tool()
    def download_signs_validation_xlsx(area: str) -> str:
        """Route-validation xlsx for an area (one row per issue + per-route summary sheet)."""
        return _json_result(c().download_signs_validation_xlsx(area))

    # =====================================================================
    # Route annotations
    # =====================================================================

    @mcp.tool()
    def list_route_annotations(
        area: str,
        rutenummer: str,
        kind: Optional[str] = None,
        include_resolved: bool = True,
    ) -> str:
        """List route annotations (rutebok / inspeksjon / dugnad / arbeid). kind filters; include_resolved=false hides resolved."""
        return _json_result(
            c().list_route_annotations(area, rutenummer, kind=kind, include_resolved=include_resolved)
        )

    @mcp.tool()
    def create_route_annotation(
        area: str,
        rutenummer: str,
        kind: str,
        title: Optional[str] = None,
        body: Optional[str] = None,
        occurred_at: Optional[str] = None,
        position_along_m: Optional[float] = None,
        lon: Optional[float] = None,
        lat: Optional[float] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Create a route annotation. kind: 'rutebok' | 'inspeksjon' | 'dugnad' | 'arbeid' | etc."""
        return _json_result(
            c().create_route_annotation(
                area=area,
                rutenummer=rutenummer,
                kind=kind,
                title=title,
                body=body,
                occurred_at=occurred_at,
                position_along_m=position_along_m,
                lon=lon,
                lat=lat,
                x_user=x_user,
            )
        )

    @mcp.tool()
    def update_route_annotation(
        annotation_id: int,
        patch: str,
        x_user: Optional[str] = None,
    ) -> str:
        """Patch an annotation. patch: JSON object with the fields to update."""
        try:
            obj = json.loads(patch)
        except json.JSONDecodeError as e:
            return _json_result({"error": "invalid_json", "detail": str(e)})
        return _json_result(c().update_route_annotation(annotation_id, obj, x_user=x_user))

    @mcp.tool()
    def delete_route_annotation(annotation_id: int, x_user: Optional[str] = None) -> str:
        """Delete a route annotation."""
        return _json_result(c().delete_route_annotation(annotation_id, x_user=x_user))

    @mcp.tool()
    def list_work_markers(area: str, include_resolved: bool = False) -> str:
        """List the area's 'arbeid'-kind annotations as work markers."""
        return _json_result(c().list_work_markers(area, include_resolved=include_resolved))

    @mcp.tool()
    def download_route_dagbok_xlsx(area: str, rutenummer: str) -> str:
        """Download the route 'dagbok' (annotation log) as xlsx."""
        return _json_result(c().download_route_dagbok_xlsx(area, rutenummer))

    # =====================================================================
    # Route correction (link exclusions + bridges) + new validation
    # =====================================================================

    @mcp.tool()
    def get_area_route_validation(area: str, rutenummer: str) -> str:
        """Per-route validation in the new area-aware shape (used by signs_app)."""
        return _json_result(c().get_area_route_validation(area, rutenummer))

    @mcp.tool()
    def list_link_exclusions(area: str, rutenummer: str) -> str:
        """List current link exclusions for a route."""
        return _json_result(c().list_link_exclusions(area, rutenummer))

    @mcp.tool()
    def add_link_exclusions(
        area: str,
        rutenummer: str,
        link_ids: str,
        reason: Optional[str] = None,
        comment: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Add link exclusions for a route. link_ids: comma-separated or JSON array of integers."""
        ids = _parse_list(link_ids) or []
        try:
            ids_int = [int(i) for i in ids]
        except (TypeError, ValueError):
            return _json_result({"error": "invalid_link_ids", "detail": "link_ids must be integers"})
        return _json_result(
            c().add_link_exclusions(area, rutenummer, ids_int, reason=reason, comment=comment, x_user=x_user)
        )

    @mcp.tool()
    def clear_link_exclusions(
        area: str,
        rutenummer: str,
        link_ids: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Clear link exclusions; if link_ids omitted, clears all for this route."""
        ids_int = None
        if link_ids:
            try:
                ids_int = [int(i) for i in (_parse_list(link_ids) or [])]
            except (TypeError, ValueError):
                return _json_result({"error": "invalid_link_ids", "detail": "link_ids must be integers"})
        return _json_result(c().clear_link_exclusions(area, rutenummer, link_ids=ids_int, x_user=x_user))

    @mcp.tool()
    def list_link_bridges(area: str, rutenummer: str) -> str:
        """List current link bridges (manual node→node connectors) for a route."""
        return _json_result(c().list_link_bridges(area, rutenummer))

    @mcp.tool()
    def add_link_bridge(
        area: str,
        rutenummer: str,
        a_node: int,
        b_node: int,
        reason: Optional[str] = None,
        comment: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Add a manual node→node bridge for a route."""
        return _json_result(
            c().add_link_bridge(
                area, rutenummer, a_node=a_node, b_node=b_node,
                reason=reason, comment=comment, x_user=x_user,
            )
        )

    @mcp.tool()
    def clear_link_bridges(
        area: str,
        rutenummer: str,
        a_node: Optional[int] = None,
        b_node: Optional[int] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Clear link bridges. Both nodes specified → clear that pair only; both None → clear all for this route."""
        if (a_node is None) != (b_node is None):
            return _json_result({"error": "invalid_args", "detail": "specify both a_node and b_node, or neither"})
        nodes = (a_node, b_node) if a_node is not None and b_node is not None else None
        return _json_result(c().clear_link_bridges(area, rutenummer, nodes=nodes, x_user=x_user))

    # =====================================================================
    # Photos
    # =====================================================================

    @mcp.tool()
    def list_photos(area: str, pending: Optional[bool] = None) -> str:
        """List photos in an area. pending=true → only the 'needs placement' tray; false → only placed; omit → both."""
        return _json_result(c().list_photos(area, pending=pending))

    @mcp.tool()
    def get_photo_thumbnails(area: str, bbox: Optional[str] = None) -> str:
        """Bulk-fetch base64 thumbnails for placed photos. bbox optional viewport clip (xmin,ymin,xmax,ymax)."""
        return _json_result(c().get_photo_thumbnails(area, bbox=bbox))

    @mcp.tool()
    def upload_photo(
        area: str,
        file_path: str,
        caption: Optional[str] = None,
        tags: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Upload one photo. file_path is on the MCP server host. tags: comma-separated or JSON array."""
        tag_list = _parse_list(tags) if tags else None
        return _json_result(
            c().upload_photo(area=area, file_path=file_path, caption=caption, tags=tag_list, x_user=x_user)
        )

    @mcp.tool()
    def patch_photo(
        photo_id: int,
        lon: Optional[float] = None,
        lat: Optional[float] = None,
        caption: Optional[str] = None,
        tags: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Patch a photo's position, caption, or tags. tags: comma-separated or JSON array."""
        tag_list = _parse_list(tags) if tags else None
        return _json_result(
            c().patch_photo(photo_id, lon=lon, lat=lat, caption=caption, tags=tag_list, x_user=x_user)
        )

    @mcp.tool()
    def delete_photo(photo_id: int, x_user: Optional[str] = None) -> str:
        """Delete a photo."""
        return _json_result(c().delete_photo(photo_id, x_user=x_user))

    @mcp.tool()
    def download_photo_file(photo_id: int) -> str:
        """Download a photo's binary to STIFLYT_MCP_ARTIFACTS_DIR; returns {path, size, content_type}."""
        return _json_result(c().download_photo_file(photo_id))

    @mcp.tool()
    def get_route_photos(area: str, rutenummer: str, radius_m: float = 75.0) -> str:
        """Photos near a route's geometry (proximity-derived, not stored)."""
        return _json_result(c().get_route_photos(area, rutenummer, radius_m=radius_m))

    # =====================================================================
    # GPX
    # =====================================================================

    @mcp.tool()
    def list_gpx_tracks(area: str) -> str:
        """List uploaded GPX tracks in an area."""
        return _json_result(c().list_gpx_tracks(area))

    @mcp.tool()
    def upload_gpx(
        area: str,
        file_path: str,
        name: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Upload one GPX file. file_path is on the MCP server host."""
        return _json_result(c().upload_gpx(area=area, file_path=file_path, name=name, x_user=x_user))

    @mcp.tool()
    def delete_gpx(track_id: int, x_user: Optional[str] = None) -> str:
        """Delete a GPX track."""
        return _json_result(c().delete_gpx(track_id, x_user=x_user))

    @mcp.tool()
    def get_route_gpx_comparison(area: str, rutenummer: str) -> str:
        """Compare a route's official geometry with overlapping GPX tracks."""
        return _json_result(c().get_route_gpx_comparison(area, rutenummer))

    # =====================================================================
    # Elevation
    # =====================================================================

    @mcp.tool()
    def get_route_elevation(area: str, rutenummer: str, refresh: bool = False) -> str:
        """Elevation profile for a route. refresh=true recomputes from DTM."""
        return _json_result(c().get_route_elevation(area, rutenummer, refresh=refresh))

    # =====================================================================
    # Metadata override (errata)
    # =====================================================================

    @mcp.tool()
    def get_metadata_override(area: str, rutenummer: str) -> str:
        """Get the metadata-override (errata) for a route, if any."""
        return _json_result(c().get_metadata_override(area, rutenummer))

    @mcp.tool()
    def put_metadata_override(
        area: str,
        rutenummer: str,
        rutenavn: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        rutetype: Optional[str] = None,
        gradering: Optional[str] = None,
        comment: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> str:
        """Upsert a metadata override (errata) for a route. Pass only fields you want to change."""
        return _json_result(
            c().put_metadata_override(
                area=area, rutenummer=rutenummer,
                rutenavn=rutenavn,
                vedlikeholdsansvarlig=vedlikeholdsansvarlig,
                rutetype=rutetype, gradering=gradering,
                comment=comment, x_user=x_user,
            )
        )

    @mcp.tool()
    def clear_metadata_override(area: str, rutenummer: str, x_user: Optional[str] = None) -> str:
        """Remove the metadata override for a route."""
        return _json_result(c().clear_metadata_override(area, rutenummer, x_user=x_user))

    # =====================================================================
    # Geometry / matrikkel
    # =====================================================================

    @mcp.tool()
    def get_geometry_owners(geometry: str) -> str:
        """Property owners along a LineString. geometry: JSON {type, coordinates}."""
        try:
            geom = json.loads(geometry)
        except json.JSONDecodeError as e:
            return _json_result({"error": "invalid_json", "detail": str(e)})
        return _json_result(c().get_geometry_owners(geom))

    @mcp.tool()
    def get_point_matrikkelenhet(lat: float, lon: float) -> str:
        """Matrikkelenhet (parcel) + optional owner info for a WGS84 point."""
        return _json_result(c().get_point_matrikkelenhet(lat, lon))

    # =====================================================================
    # Changesets
    # =====================================================================

    @mcp.tool()
    def list_changesets(limit: int = 100, offset: int = 0) -> str:
        """List all changesets."""
        return _json_result(c().list_changesets(limit=limit, offset=offset))

    @mcp.tool()
    def create_changeset(
        title: str,
        description: Optional[str] = None,
        area: Optional[str] = None,
        linked_issue_url: Optional[str] = None,
        base_snapshot: str = "default",
        x_user: Optional[str] = None,
    ) -> str:
        """Create a new changeset."""
        return _json_result(
            c().create_changeset(
                title=title,
                description=description,
                area=area,
                linked_issue_url=linked_issue_url,
                base_snapshot=base_snapshot,
                x_user=x_user,
            )
        )

    @mcp.tool()
    def get_changeset(changeset_id: str) -> str:
        """Get a changeset by ID."""
        return _json_result(c().get_changeset(changeset_id))

    @mcp.tool()
    def add_changeset_event(changeset_id: str, event: str, x_user: Optional[str] = None) -> str:
        """Add an event to a changeset. event: JSON object (type, target, patch/geometry/etc)."""
        try:
            ev = json.loads(event)
        except json.JSONDecodeError as e:
            return _json_result({"error": "invalid_json", "detail": str(e)})
        return _json_result(c().add_changeset_event(changeset_id, ev, x_user=x_user))

    @mcp.tool()
    def get_changeset_events(changeset_id: str) -> str:
        """All events for a changeset."""
        return _json_result(c().get_changeset_events(changeset_id))

    @mcp.tool()
    def validate_changeset(changeset_id: str) -> str:
        """Validate a changeset."""
        return _json_result(c().validate_changeset(changeset_id))

    @mcp.tool()
    def get_changeset_diff_geojson(changeset_id: str) -> str:
        """Diff GeoJSON for a changeset."""
        return _json_result(c().get_changeset_diff_geojson(changeset_id))

    @mcp.tool()
    def get_changeset_effective_geojson(changeset_id: str) -> str:
        """Effective GeoJSON (base + changes) for a changeset."""
        return _json_result(c().get_changeset_effective_geojson(changeset_id))

    @mcp.tool()
    def get_changeset_artifact(changeset_id: str, filename: str) -> str:
        """Download a changeset artifact (JSON only). filename must end with .json."""
        return _json_result(c().get_changeset_artifact(changeset_id, filename))

    @mcp.tool()
    def publish_changeset(changeset_id: str, x_user: Optional[str] = None) -> str:
        """Publish a changeset (send to review)."""
        return _json_result(c().publish_changeset(changeset_id, x_user=x_user))

    # =====================================================================
    # Editor
    # =====================================================================

    @mcp.tool()
    def get_snap_targets(bbox: str) -> str:
        """Snap targets for a bounding box (min_lon,min_lat,max_lon,max_lat)."""
        return _json_result(c().get_snap_targets(bbox))

    return mcp
