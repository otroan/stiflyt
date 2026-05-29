"""HTTP client for the Stiflyt backend API.

Auth model
----------
- The backend gates /api/v1/* behind a Google OAuth session by default. For
  automation (this MCP server) the backend can be configured with
  STIFLYT_API_KEY; when set, the client sends the same value as the
  X-API-Key header and the side-door dep (api/auth.py::require_user_or_api_key)
  lets the request through.
- Every mutating route reads X-User from the request header to record
  recorded_by / updated_by / uploaded_by. Set STIFLYT_X_USER in the client
  env so all mutations get attributed to a real person; individual calls
  may override via the `x_user` kwarg.
- The legacy Basic-auth credential pair (STIFLYT_USERNAME/_PASSWORD) is still
  supported; it only applies to the few endpoints behind require_shared_login
  (currently just /owners.xlsx).

Binary downloads
----------------
- xlsx / pdf endpoints write the payload to STIFLYT_MCP_ARTIFACTS_DIR
  (default /tmp/stiflyt-mcp) and return {path, size, content_type} so the
  MCP tool result stays JSON-clean. The path is on the host where the
  MCP server runs, which may be remote — `scp` to retrieve.
"""
import os
import json
import re
import uuid
from pathlib import Path
from typing import Any, Optional
import requests
from requests.auth import HTTPBasicAuth

DEFAULT_BASE_URL = "http://localhost:8001"
DEFAULT_ARTIFACTS_DIR = "/tmp/stiflyt-mcp"


class StiflytClient:
    """Client for Stiflyt backend API.

    Env vars consumed (only at first instantiation):
        STIFLYT_BASE_URL          backend root (default http://localhost:8001)
        STIFLYT_API_KEY           side-door key sent as X-API-Key
        STIFLYT_X_USER            default X-User for mutation attribution
        STIFLYT_USERNAME          legacy Basic auth (owners.xlsx only)
        STIFLYT_PASSWORD          legacy Basic auth (owners.xlsx only)
        STIFLYT_MCP_ARTIFACTS_DIR where binary downloads land (default /tmp/stiflyt-mcp)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_key: Optional[str] = None,
        default_x_user: Optional[str] = None,
        artifacts_dir: Optional[str] = None,
    ):
        self.base_url = (base_url or os.getenv("STIFLYT_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or os.getenv("STIFLYT_API_KEY") or None
        self.default_x_user = default_x_user or os.getenv("STIFLYT_X_USER") or None
        self.artifacts_dir = Path(artifacts_dir or os.getenv("STIFLYT_MCP_ARTIFACTS_DIR") or DEFAULT_ARTIFACTS_DIR)
        self.auth = None
        if username or os.getenv("STIFLYT_USERNAME"):
            u = username or os.getenv("STIFLYT_USERNAME", "")
            p = password or os.getenv("STIFLYT_PASSWORD", "")
            if u and p:
                self.auth = HTTPBasicAuth(u, p)

    # --- transport ---------------------------------------------------------

    def _default_headers(self, x_user: Optional[str] = None) -> dict:
        h: dict = {}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        actor = x_user or self.default_x_user
        if actor:
            h["X-User"] = actor
        return h

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[Any] = None,
        headers: Optional[dict] = None,
        x_user: Optional[str] = None,
        files: Optional[dict] = None,
        data: Optional[dict] = None,
        raw: bool = False,
    ) -> Any:
        """Send a request. raw=True returns the requests.Response unchanged
        so callers can stream binary content; otherwise returns parsed JSON
        or an error dict.
        """
        url = f"{self.base_url}{path}"
        h = self._default_headers(x_user)
        if headers:
            h.update(headers)
        if json_body is not None and files is None and "Content-Type" not in h:
            h["Content-Type"] = "application/json"
        try:
            r = requests.request(
                method,
                url,
                params=params,
                json=json_body if files is None else None,
                data=data,
                files=files,
                headers=h,
                auth=self.auth,
                timeout=120,
            )
            if raw:
                return r
            if r.status_code == 204:
                return {"ok": True, "status": 204}
            if r.status_code >= 400:
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            ct = r.headers.get("Content-Type", "")
            if "application/json" in ct:
                return r.json()
            if r.text == "":
                return {"ok": True, "status": r.status_code}
            return {"content": r.text[:2000], "content_type": ct}
        except requests.RequestException as e:
            return {"error": "request_failed", "detail": str(e)}

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        json_body: Optional[Any] = None,
        params: Optional[dict] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        return self._request("POST", path, params=params, json_body=json_body, x_user=x_user)

    def patch(
        self,
        path: str,
        json_body: Optional[Any] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        return self._request("PATCH", path, json_body=json_body, x_user=x_user)

    def put(
        self,
        path: str,
        json_body: Optional[Any] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        return self._request("PUT", path, json_body=json_body, x_user=x_user)

    def delete(
        self,
        path: str,
        params: Optional[dict] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        return self._request("DELETE", path, params=params, x_user=x_user)

    # --- binary download helper -------------------------------------------

    def _download(
        self,
        method: str,
        path: str,
        suggested_ext: str,
        params: Optional[dict] = None,
        json_body: Optional[Any] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        """Stream a binary response to artifacts_dir; return path + metadata."""
        r = self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            x_user=x_user,
            raw=True,
        )
        if isinstance(r, dict):  # request_failed dict from _request
            return r
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
        try:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"error": "artifacts_dir_unwritable", "detail": str(e), "path": str(self.artifacts_dir)}

        cd = r.headers.get("Content-Disposition", "")
        m = re.search(r'filename="?([^"]+)"?', cd)
        if m:
            fname = m.group(1)
        else:
            slug = path.strip("/").replace("/", "_") or "download"
            fname = f"{slug}-{uuid.uuid4().hex[:8]}{suggested_ext}"

        out = self.artifacts_dir / fname
        out.write_bytes(r.content)
        return {
            "path": str(out),
            "size": len(r.content),
            "content_type": r.headers.get("Content-Type", "application/octet-stream"),
            "filename": fname,
        }

    # --- multipart upload helper ------------------------------------------

    def _upload(
        self,
        path: str,
        file_path: str,
        form: Optional[dict] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        p = Path(file_path)
        if not p.exists():
            return {"error": "file_not_found", "detail": str(p)}
        if not p.is_file():
            return {"error": "not_a_file", "detail": str(p)}
        try:
            with open(p, "rb") as fh:
                files = {"file": (p.name, fh)}
                return self._request(
                    "POST",
                    path,
                    data=form or {},
                    files=files,
                    x_user=x_user,
                )
        except OSError as e:
            return {"error": "file_unreadable", "detail": str(e)}

    # =====================================================================
    # Search
    # =====================================================================

    def search_places(self, q: str, limit: int = 20) -> Any:
        return self.get("/api/v1/search/places", params={"q": q, "limit": limit})

    # =====================================================================
    # Routes
    # =====================================================================

    def get_routes(
        self,
        prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        bbox: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_geometry: bool = False,
    ) -> Any:
        p: dict = {"limit": limit, "offset": offset, "include_geometry": include_geometry}
        if prefix:
            p["prefix"] = prefix
        if vedlikeholdsansvarlig:
            p["vedlikeholdsansvarlig"] = vedlikeholdsansvarlig
        if bbox:
            p["bbox"] = bbox
        return self.get("/api/v1/routes", params=p)

    def get_route(self, rutenummer: str, include_geometry: bool = False) -> Any:
        return self.get(f"/api/v1/routes/{rutenummer}", params={"include_geometry": include_geometry})

    def get_route_complete(
        self,
        rutenummer: str,
        include_geometry: bool = True,
        include_segments: bool = False,
        include_endpoint_names: bool = True,
    ) -> Any:
        return self.get(
            f"/api/v1/routes/{rutenummer}/complete",
            params={
                "include_geometry": include_geometry,
                "include_segments": include_segments,
                "include_endpoint_names": include_endpoint_names,
            },
        )

    def get_route_segments(self, rutenummer: str, include_geometry: bool = False) -> Any:
        return self.get(
            f"/api/v1/routes/{rutenummer}/segments",
            params={"include_geometry": include_geometry},
        )

    def get_route_links(self, rutenummer: str, include_geometry: bool = False) -> Any:
        return self.get(
            f"/api/v1/routes/{rutenummer}/links",
            params={"include_geometry": include_geometry},
        )

    def validate_route(self, rutenummer: str) -> Any:
        return self.get(f"/api/v1/routes/{rutenummer}/validate")

    def get_routes_statistics(
        self,
        prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        bbox: Optional[str] = None,
    ) -> Any:
        p: dict = {}
        if prefix:
            p["prefix"] = prefix
        if vedlikeholdsansvarlig:
            p["vedlikeholdsansvarlig"] = vedlikeholdsansvarlig
        if bbox:
            p["bbox"] = bbox
        return self.get("/api/v1/routes/statistics", params=p)

    def get_route_areas(
        self,
        vedlikeholdsansvarlig: Optional[str] = None,
        debug: bool = False,
        debug_prefix: Optional[str] = None,
    ) -> Any:
        p: dict = {"debug": debug}
        if vedlikeholdsansvarlig:
            p["vedlikeholdsansvarlig"] = vedlikeholdsansvarlig
        if debug_prefix:
            p["debug_prefix"] = debug_prefix
        return self.get("/api/v1/routes/areas", params=p)

    def get_routes_bulk(self, rutenummer: str, include_geometry: bool = False) -> Any:
        return self.get(
            "/api/v1/routes/bulk",
            params={"rutenummer": rutenummer, "include_geometry": include_geometry},
        )

    # =====================================================================
    # Segments
    # =====================================================================

    def get_route_segments_list(
        self,
        rutenummer_prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_geometry: bool = False,
    ) -> Any:
        p: dict = {"limit": limit, "offset": offset, "include_geometry": include_geometry}
        if rutenummer_prefix:
            p["rutenummer_prefix"] = rutenummer_prefix
        if vedlikeholdsansvarlig:
            p["vedlikeholdsansvarlig"] = vedlikeholdsansvarlig
        return self.get("/api/v1/routes/segments", params=p)

    def get_segment_routes(self, segment_objid: int) -> Any:
        return self.get(f"/api/v1/segments/{segment_objid}/routes")

    def get_segment_by_lokalid(self, lokalid: str) -> Any:
        return self.get(f"/api/v1/segments/by-lokalid/{lokalid}")

    # =====================================================================
    # Links / anchor nodes
    # =====================================================================

    def get_links(
        self,
        bbox: str,
        limit: int = 500,
        offset: int = 0,
        rutenummer_prefix: Optional[str] = None,
    ) -> Any:
        p: dict = {"bbox": bbox, "limit": limit, "offset": offset}
        if rutenummer_prefix:
            p["rutenummer_prefix"] = rutenummer_prefix
        return self.get("/api/v1/links", params=p)

    def get_anchor_nodes(
        self,
        node_ids: Optional[str] = None,
        bbox: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Any:
        p: dict = {"limit": limit, "offset": offset}
        if node_ids:
            p["node_ids"] = node_ids
        if bbox:
            p["bbox"] = bbox
        return self.get("/api/v1/anchor-nodes", params=p)

    # =====================================================================
    # Route anchors (the original endpoint set)
    # =====================================================================

    def get_route_anchors(self, rutenummer: str) -> Any:
        return self.get(f"/api/v1/routes/{rutenummer}/anchors")

    def get_anchor_placenames(self, anchor_id: int, radius: int = 500, limit: int = 12) -> Any:
        return self.get(
            f"/api/v1/anchors/{anchor_id}/placenames",
            params={"radius": radius, "limit": limit},
        )

    def upsert_anchor_name(
        self,
        anchor_id: int,
        name: str,
        source_type: str,
        source_id: Optional[str] = None,
        distance_meters: Optional[float] = None,
        rutenummer: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        body: dict = {"name": name, "source_type": source_type}
        if source_id is not None:
            body["source_id"] = source_id
        if distance_meters is not None:
            body["distance_meters"] = distance_meters
        if rutenummer is not None:
            body["rutenummer"] = rutenummer
        return self.post(f"/api/v1/anchors/{anchor_id}/name", json_body=body, x_user=x_user)

    # =====================================================================
    # Signs — legacy reports
    # =====================================================================

    def get_route_signs(self, rutenummer: str) -> Any:
        return self.get(f"/api/v1/routes/{rutenummer}/signs")

    def get_signs_by_prefix(self, prefix: Optional[str] = None) -> Any:
        return self.get("/api/v1/signs", params={"prefix": prefix} if prefix else None)

    def get_signs_missing(self, prefix: str) -> Any:
        return self.get("/api/v1/signs/missing", params={"prefix": prefix})

    def get_signs_production(self, prefix: str) -> Any:
        return self.get("/api/v1/signs/production", params={"prefix": prefix})

    def get_route_signs_production(self, rutenummer: str) -> Any:
        return self.get(f"/api/v1/routes/{rutenummer}/signs/production")

    # =====================================================================
    # Signs — signs_app candidate / area workflow
    # =====================================================================

    def get_signs_candidates(self, area: str) -> Any:
        return self.get(f"/api/v1/signs/candidates/{area}")

    def get_signs_area_routes(self, area: str) -> Any:
        return self.get(f"/api/v1/signs/area/{area}/routes")

    def get_signs_area_stats(self, area: str) -> Any:
        return self.get(f"/api/v1/signs/area/{area}/stats")

    def get_signs_area_validation(self, area: str, refresh: bool = False) -> Any:
        return self.get(
            f"/api/v1/signs/area/{area}/validation",
            params={"refresh": 1} if refresh else None,
        )

    def accept_sign_candidate(self, area: str, anchor_node_id: int, x_user: Optional[str] = None) -> Any:
        return self.post(
            f"/api/v1/signs/candidates/{area}/anchors/{anchor_node_id}/accept",
            json_body={},
            x_user=x_user,
        )

    def reject_sign_candidate(self, area: str, anchor_node_id: int, x_user: Optional[str] = None) -> Any:
        return self.post(
            f"/api/v1/signs/candidates/{area}/anchors/{anchor_node_id}/reject",
            json_body={},
            x_user=x_user,
        )

    def create_manual_sign(
        self,
        area: str,
        rutenummer_list: list,
        lon: float,
        lat: float,
        name: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        body: dict = {"rutenummer_list": rutenummer_list, "lon": lon, "lat": lat}
        if name is not None:
            body["name"] = name
        return self.post(
            f"/api/v1/signs/candidates/{area}/manual",
            json_body=body,
            x_user=x_user,
        )

    # --- placenames probe (signs_app variant: by coordinate) --------------

    def get_signs_placenames(self, lon: float, lat: float, radius: int = 500, limit: int = 12) -> Any:
        return self.get(
            "/api/v1/signs/placenames",
            params={"lon": lon, "lat": lat, "radius": radius, "limit": limit},
        )

    # --- anchor name (signs_app variant — simpler payload) ----------------

    def upsert_signs_anchor_name(self, anchor_id: int, name: str, x_user: Optional[str] = None) -> Any:
        return self.post(
            f"/api/v1/signs/anchors/{anchor_id}/name",
            json_body={"name": name},
            x_user=x_user,
        )

    # --- sign sites & panels ----------------------------------------------

    def update_sign_site_name(self, sign_site_id: int, name: str, x_user: Optional[str] = None) -> Any:
        return self.patch(
            f"/api/v1/signs/sites/{sign_site_id}",
            json_body={"name": name},
            x_user=x_user,
        )

    def update_sign_site_status(self, sign_site_id: int, status_value: str, x_user: Optional[str] = None) -> Any:
        return self.patch(
            f"/api/v1/signs/sites/{sign_site_id}/status",
            json_body={"status": status_value},
            x_user=x_user,
        )

    def delete_sign_site(self, sign_site_id: int, x_user: Optional[str] = None) -> Any:
        return self.delete(f"/api/v1/signs/sites/{sign_site_id}", x_user=x_user)

    def patch_sign_panel(
        self,
        sign_site_id: int,
        destination_anchor_node_id: int,
        color: Optional[str] = None,
        direction: Optional[str] = None,
        distance_km: Optional[float] = None,
        destination_name: Optional[str] = None,
        first_link_id: Optional[int] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        body: dict = {}
        if color is not None:
            body["color"] = color
        if direction is not None:
            body["direction"] = direction
        if distance_km is not None:
            body["distance_km"] = distance_km
        if destination_name is not None:
            body["destination_name"] = destination_name
        if first_link_id is not None:
            body["first_link_id"] = first_link_id
        return self.patch(
            f"/api/v1/signs/sites/{sign_site_id}/panels/{destination_anchor_node_id}/edit",
            json_body=body,
            x_user=x_user,
        )

    def get_sign_site_destinations(self, sign_site_id: int) -> Any:
        return self.get(f"/api/v1/signs/sites/{sign_site_id}/destinations")

    def set_sign_site_destinations(
        self,
        sign_site_id: int,
        destinations: list,
        x_user: Optional[str] = None,
    ) -> Any:
        return self.put(
            f"/api/v1/signs/sites/{sign_site_id}/destinations",
            json_body={"destinations": destinations},
            x_user=x_user,
        )

    def patch_sign_destination_skilt(
        self,
        sign_site_id: int,
        anchor_node_id: int,
        payload: dict,
        x_user: Optional[str] = None,
    ) -> Any:
        return self.patch(
            f"/api/v1/signs/sites/{sign_site_id}/destinations/{anchor_node_id}/skilt",
            json_body=payload,
            x_user=x_user,
        )

    # --- exports (binary) -------------------------------------------------

    def download_signs_manufacturing_xlsx(self, area: str, panels: Optional[list] = None) -> Any:
        if panels:
            return self._download(
                "POST",
                f"/api/v1/signs/manufacturing/{area}.xlsx",
                suggested_ext=".xlsx",
                json_body={"panels": panels},
            )
        return self._download(
            "GET",
            f"/api/v1/signs/manufacturing/{area}.xlsx",
            suggested_ext=".xlsx",
        )

    def download_signs_field_pdf(self, area: str, panels: Optional[list] = None) -> Any:
        if panels:
            return self._download(
                "POST",
                f"/api/v1/signs/field-pdf/{area}.pdf",
                suggested_ext=".pdf",
                json_body={"panels": panels},
            )
        return self._download(
            "GET",
            f"/api/v1/signs/field-pdf/{area}.pdf",
            suggested_ext=".pdf",
        )

    def download_signs_validation_xlsx(self, area: str) -> Any:
        return self._download(
            "GET",
            f"/api/v1/signs/validation/{area}.xlsx",
            suggested_ext=".xlsx",
        )

    def download_owners_xlsx(self, payload: dict) -> Any:
        return self._download(
            "POST",
            "/api/v1/owners.xlsx",
            suggested_ext=".xlsx",
            json_body=payload,
        )

    # =====================================================================
    # Route annotations (rutebok / inspeksjon / dugnad / arbeid)
    # =====================================================================

    def list_route_annotations(
        self,
        area: str,
        rutenummer: str,
        kind: Optional[str] = None,
        include_resolved: bool = True,
    ) -> Any:
        p: dict = {}
        if kind:
            p["kind"] = kind
        if include_resolved is False:
            p["include_resolved"] = "false"
        return self.get(
            f"/api/v1/routes/{area}/{rutenummer}/annotations",
            params=p or None,
        )

    def create_route_annotation(
        self,
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
    ) -> Any:
        payload: dict = {"kind": kind}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if occurred_at is not None:
            payload["occurred_at"] = occurred_at
        if position_along_m is not None:
            payload["position_along_m"] = position_along_m
        if lon is not None:
            payload["lon"] = lon
        if lat is not None:
            payload["lat"] = lat
        return self.post(
            f"/api/v1/routes/{area}/{rutenummer}/annotations",
            json_body=payload,
            x_user=x_user,
        )

    def update_route_annotation(self, annotation_id: int, patch: dict, x_user: Optional[str] = None) -> Any:
        return self.patch(
            f"/api/v1/route-annotations/{annotation_id}",
            json_body=patch,
            x_user=x_user,
        )

    def delete_route_annotation(self, annotation_id: int, x_user: Optional[str] = None) -> Any:
        return self.delete(f"/api/v1/route-annotations/{annotation_id}", x_user=x_user)

    def list_work_markers(self, area: str, include_resolved: bool = False) -> Any:
        p = {"include_resolved": "true"} if include_resolved else None
        return self.get(f"/api/v1/routes/{area}/work-markers", params=p)

    def download_route_dagbok_xlsx(self, area: str, rutenummer: str) -> Any:
        return self._download(
            "GET",
            f"/api/v1/routes/{area}/{rutenummer}/dagbok.xlsx",
            suggested_ext=".xlsx",
        )

    # =====================================================================
    # Route correction (link exclusions + link bridges) + new validation
    # =====================================================================

    def get_area_route_validation(self, area: str, rutenummer: str) -> Any:
        return self.get(f"/api/v1/routes/{area}/{rutenummer}/validation")

    def list_link_exclusions(self, area: str, rutenummer: str) -> Any:
        return self.get(f"/api/v1/routes/{area}/{rutenummer}/link-exclusions")

    def add_link_exclusions(
        self,
        area: str,
        rutenummer: str,
        link_ids: list,
        reason: Optional[str] = None,
        comment: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        body: dict = {"link_ids": link_ids}
        if reason is not None:
            body["reason"] = reason
        if comment is not None:
            body["comment"] = comment
        return self.post(
            f"/api/v1/routes/{area}/{rutenummer}/link-exclusions",
            json_body=body,
            x_user=x_user,
        )

    def clear_link_exclusions(
        self,
        area: str,
        rutenummer: str,
        link_ids: Optional[list] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        params = {"link_ids": ",".join(str(i) for i in link_ids)} if link_ids else None
        return self.delete(
            f"/api/v1/routes/{area}/{rutenummer}/link-exclusions",
            params=params,
            x_user=x_user,
        )

    def list_link_bridges(self, area: str, rutenummer: str) -> Any:
        return self.get(f"/api/v1/routes/{area}/{rutenummer}/link-bridges")

    def add_link_bridge(
        self,
        area: str,
        rutenummer: str,
        a_node: int,
        b_node: int,
        reason: Optional[str] = None,
        comment: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        body: dict = {"a_node": a_node, "b_node": b_node}
        if reason is not None:
            body["reason"] = reason
        if comment is not None:
            body["comment"] = comment
        return self.post(
            f"/api/v1/routes/{area}/{rutenummer}/link-bridges",
            json_body=body,
            x_user=x_user,
        )

    def clear_link_bridges(
        self,
        area: str,
        rutenummer: str,
        nodes: Optional[tuple] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        params = {"nodes": f"{nodes[0]}-{nodes[1]}"} if nodes else None
        return self.delete(
            f"/api/v1/routes/{area}/{rutenummer}/link-bridges",
            params=params,
            x_user=x_user,
        )

    # =====================================================================
    # Photos
    # =====================================================================

    def list_photos(self, area: str, pending: Optional[bool] = None) -> Any:
        p: dict = {"area": area}
        if pending is not None:
            p["pending"] = "true" if pending else "false"
        return self.get("/api/v1/photos", params=p)

    def get_photo_thumbnails(
        self,
        area: str,
        bbox: Optional[str] = None,
    ) -> Any:
        p: dict = {"area": area}
        if bbox:
            p["bbox"] = bbox
        return self.get("/api/v1/photos/thumbnails", params=p)

    def upload_photo(
        self,
        area: str,
        file_path: str,
        caption: Optional[str] = None,
        tags: Optional[list] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        # requests' `data` accepts a list of tuples for repeated keys (tags=foo&tags=bar).
        form: list = [("area", area)]
        if caption is not None:
            form.append(("caption", caption))
        for t in tags or []:
            form.append(("tags", t))
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return {"error": "file_not_found", "detail": str(p)}
        try:
            with open(p, "rb") as fh:
                files = {"file": (p.name, fh)}
                return self._request(
                    "POST",
                    "/api/v1/photos",
                    data=form,
                    files=files,
                    x_user=x_user,
                )
        except OSError as e:
            return {"error": "file_unreadable", "detail": str(e)}

    def patch_photo(
        self,
        photo_id: int,
        lon: Optional[float] = None,
        lat: Optional[float] = None,
        caption: Optional[str] = None,
        tags: Optional[list] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        body: dict = {}
        if lon is not None:
            body["lon"] = lon
        if lat is not None:
            body["lat"] = lat
        if caption is not None:
            body["caption"] = caption
        if tags is not None:
            body["tags"] = tags
        return self.patch(f"/api/v1/photos/{photo_id}", json_body=body, x_user=x_user)

    def delete_photo(self, photo_id: int, x_user: Optional[str] = None) -> Any:
        return self.delete(f"/api/v1/photos/{photo_id}", x_user=x_user)

    def download_photo_file(self, photo_id: int) -> Any:
        return self._download(
            "GET",
            f"/api/v1/photos/{photo_id}/file",
            suggested_ext=".jpg",
        )

    def get_route_photos(self, area: str, rutenummer: str, radius_m: float = 75.0) -> Any:
        return self.get(
            f"/api/v1/routes/{area}/{rutenummer}/photos",
            params={"radius_m": radius_m},
        )

    # =====================================================================
    # GPX tracks
    # =====================================================================

    def list_gpx_tracks(self, area: str) -> Any:
        return self.get("/api/v1/gpx", params={"area": area})

    def upload_gpx(
        self,
        area: str,
        file_path: str,
        name: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        form: list = [("area", area)]
        if name:
            form.append(("name", name))
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return {"error": "file_not_found", "detail": str(p)}
        try:
            with open(p, "rb") as fh:
                files = {"file": (p.name, fh)}
                return self._request(
                    "POST",
                    "/api/v1/gpx",
                    data=form,
                    files=files,
                    x_user=x_user,
                )
        except OSError as e:
            return {"error": "file_unreadable", "detail": str(e)}

    def delete_gpx(self, track_id: int, x_user: Optional[str] = None) -> Any:
        return self.delete(f"/api/v1/gpx/{track_id}", x_user=x_user)

    def get_route_gpx_comparison(self, area: str, rutenummer: str) -> Any:
        return self.get(f"/api/v1/routes/{area}/{rutenummer}/gpx-comparison")

    # =====================================================================
    # Elevation
    # =====================================================================

    def get_route_elevation(self, area: str, rutenummer: str, refresh: bool = False) -> Any:
        return self.get(
            f"/api/v1/routes/{area}/{rutenummer}/elevation",
            params={"refresh": 1} if refresh else None,
        )

    # =====================================================================
    # Metadata override
    # =====================================================================

    def get_metadata_override(self, area: str, rutenummer: str) -> Any:
        return self.get(f"/api/v1/routes/{area}/{rutenummer}/metadata-override")

    def put_metadata_override(
        self,
        area: str,
        rutenummer: str,
        rutenavn: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        rutetype: Optional[str] = None,
        gradering: Optional[str] = None,
        comment: Optional[str] = None,
        x_user: Optional[str] = None,
    ) -> Any:
        body: dict = {}
        for k, v in (
            ("rutenavn", rutenavn),
            ("vedlikeholdsansvarlig", vedlikeholdsansvarlig),
            ("rutetype", rutetype),
            ("gradering", gradering),
            ("comment", comment),
        ):
            if v is not None:
                body[k] = v
        return self.put(
            f"/api/v1/routes/{area}/{rutenummer}/metadata-override",
            json_body=body,
            x_user=x_user,
        )

    def clear_metadata_override(self, area: str, rutenummer: str, x_user: Optional[str] = None) -> Any:
        return self.delete(
            f"/api/v1/routes/{area}/{rutenummer}/metadata-override",
            x_user=x_user,
        )

    # =====================================================================
    # Geometry / matrikkel
    # =====================================================================

    def get_geometry_owners(self, geometry: dict) -> Any:
        return self.post("/api/v1/geometry/owners", json_body={"geometry": geometry})

    def get_point_matrikkelenhet(self, lat: float, lon: float) -> Any:
        return self.post("/api/v1/point/matrikkelenhet", json_body={"lat": lat, "lon": lon})

    # =====================================================================
    # Changesets
    # =====================================================================

    def list_changesets(self, limit: int = 100, offset: int = 0) -> Any:
        return self.get("/api/changesets", params={"limit": limit, "offset": offset})

    def create_changeset(
        self,
        title: str,
        description: Optional[str] = None,
        area: Optional[str] = None,
        linked_issue_url: Optional[str] = None,
        base_snapshot: str = "default",
        x_user: Optional[str] = None,
    ) -> Any:
        body: dict = {"title": title, "base_snapshot": base_snapshot}
        if description is not None:
            body["description"] = description
        if area is not None:
            body["area"] = area
        if linked_issue_url is not None:
            body["linked_issue_url"] = linked_issue_url
        return self.post("/api/changesets", json_body=body, x_user=x_user)

    def get_changeset(self, changeset_id: str) -> Any:
        return self.get(f"/api/changesets/{changeset_id}")

    def add_changeset_event(self, changeset_id: str, event: dict, x_user: Optional[str] = None) -> Any:
        return self.post(
            f"/api/changesets/{changeset_id}/events",
            json_body={"event": event},
            x_user=x_user,
        )

    def get_changeset_events(self, changeset_id: str) -> Any:
        return self.get(f"/api/changesets/{changeset_id}/events")

    def validate_changeset(self, changeset_id: str) -> Any:
        return self.post(f"/api/changesets/{changeset_id}/validate")

    def get_changeset_diff_geojson(self, changeset_id: str) -> Any:
        return self.get(f"/api/changesets/{changeset_id}/diff.geojson")

    def get_changeset_effective_geojson(self, changeset_id: str) -> Any:
        return self.get(f"/api/changesets/{changeset_id}/effective.geojson")

    def get_changeset_artifact(self, changeset_id: str, filename: str) -> Any:
        return self.get(f"/api/changesets/{changeset_id}/artifacts/{filename}")

    def publish_changeset(self, changeset_id: str, x_user: Optional[str] = None) -> Any:
        return self.post(f"/api/changesets/{changeset_id}/publish", x_user=x_user)

    # =====================================================================
    # Editor
    # =====================================================================

    def get_snap_targets(self, bbox: str) -> Any:
        return self.get("/api/snap-targets", params={"bbox": bbox})

    # =====================================================================
    # Session / health
    # =====================================================================

    def get_me(self) -> Any:
        return self.get("/api/v1/auth/me")

    def health(self) -> Any:
        return self.get("/health")


def _json_result(obj: Any) -> str:
    """Serialize result for MCP tool response."""
    if isinstance(obj, dict) and "error" in obj:
        return json.dumps(obj, ensure_ascii=False)
    return json.dumps(obj, ensure_ascii=False, default=str)
