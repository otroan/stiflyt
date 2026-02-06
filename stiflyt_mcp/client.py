"""HTTP client for the Stiflyt backend API."""
import os
import json
from typing import Any, Optional
import requests
from requests.auth import HTTPBasicAuth

DEFAULT_BASE_URL = "http://localhost:8001"


class StiflytClient:
    """Client for Stiflyt backend API. Uses STIFLYT_BASE_URL and optional Basic auth from env."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.base_url = (base_url or os.getenv("STIFLYT_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.auth = None
        if username or os.getenv("STIFLYT_USERNAME"):
            u = username or os.getenv("STIFLYT_USERNAME", "")
            p = password or os.getenv("STIFLYT_PASSWORD", "")
            if u and p:
                self.auth = HTTPBasicAuth(u, p)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        h = dict(headers or {})
        if json_body is not None and "Content-Type" not in h:
            h["Content-Type"] = "application/json"
        try:
            r = requests.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=h,
                auth=self.auth,
                timeout=60,
            )
            if r.status_code >= 400:
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            ct = r.headers.get("Content-Type", "")
            if "application/json" in ct:
                return r.json()
            return {"content": r.text[:2000], "content_type": ct}
        except requests.RequestException as e:
            return {"error": "request_failed", "detail": str(e)}

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, json_body: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        return self._request("POST", path, params=params, json_body=json_body)

    # --- Search ---
    def search_places(self, q: str, limit: int = 20) -> Any:
        return self.get("/api/v1/search/places", params={"q": q, "limit": limit})

    # --- Routes ---
    def get_routes(
        self,
        prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        bbox: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_geometry: bool = False,
    ) -> Any:
        p = {"limit": limit, "offset": offset, "include_geometry": include_geometry}
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
        p = {}
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
        p = {"debug": debug}
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

    # --- Segments ---
    def get_route_segments_list(
        self,
        rutenummer_prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_geometry: bool = False,
    ) -> Any:
        p = {"limit": limit, "offset": offset, "include_geometry": include_geometry}
        if rutenummer_prefix:
            p["rutenummer_prefix"] = rutenummer_prefix
        if vedlikeholdsansvarlig:
            p["vedlikeholdsansvarlig"] = vedlikeholdsansvarlig
        return self.get("/api/v1/routes/segments", params=p)

    def get_segment_routes(self, segment_objid: int) -> Any:
        return self.get(f"/api/v1/segments/{segment_objid}/routes")

    def get_segment_by_lokalid(self, lokalid: str) -> Any:
        return self.get(f"/api/v1/segments/by-lokalid/{lokalid}")

    # --- Links / anchor-nodes ---
    def get_links(
        self,
        bbox: str,
        limit: int = 500,
        offset: int = 0,
        rutenummer_prefix: Optional[str] = None,
    ) -> Any:
        p = {"bbox": bbox, "limit": limit, "offset": offset}
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
        p = {"limit": limit, "offset": offset}
        if node_ids:
            p["node_ids"] = node_ids
        if bbox:
            p["bbox"] = bbox
        return self.get("/api/v1/anchor-nodes", params=p)

    # --- Route anchors ---
    def get_route_anchors(self, rutenummer: str) -> Any:
        return self.get(f"/api/v1/routes/{rutenummer}/anchors")

    def get_anchor_placenames(self, anchor_id: int) -> Any:
        return self.get(f"/api/v1/anchors/{anchor_id}/placenames")

    def upsert_anchor_name(
        self,
        anchor_id: int,
        name: str,
        source_type: str,
        source_id: Optional[str] = None,
        distance_meters: Optional[float] = None,
        rutenummer: Optional[str] = None,
    ) -> Any:
        body = {"name": name, "source_type": source_type}
        if source_id is not None:
            body["source_id"] = source_id
        if distance_meters is not None:
            body["distance_meters"] = distance_meters
        if rutenummer is not None:
            body["rutenummer"] = rutenummer
        return self.post(f"/api/v1/anchors/{anchor_id}/name", json_body=body)

    # --- Signs ---
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

    # --- Geometry / matrikkel ---
    def get_geometry_owners(self, geometry: dict) -> Any:
        return self.post("/api/v1/geometry/owners", json_body={"geometry": geometry})

    def get_point_matrikkelenhet(self, lat: float, lon: float) -> Any:
        return self.post("/api/v1/point/matrikkelenhet", json_body={"lat": lat, "lon": lon})

    # --- Changesets ---
    def list_changesets(self, limit: int = 100, offset: int = 0) -> Any:
        return self.get("/api/changesets", params={"limit": limit, "offset": offset})

    def create_changeset(
        self,
        title: str,
        description: Optional[str] = None,
        area: Optional[str] = None,
        linked_issue_url: Optional[str] = None,
        base_snapshot: str = "default",
    ) -> Any:
        body = {"title": title, "base_snapshot": base_snapshot}
        if description is not None:
            body["description"] = description
        if area is not None:
            body["area"] = area
        if linked_issue_url is not None:
            body["linked_issue_url"] = linked_issue_url
        return self.post("/api/changesets", json_body=body)

    def get_changeset(self, changeset_id: str) -> Any:
        return self.get(f"/api/changesets/{changeset_id}")

    def add_changeset_event(self, changeset_id: str, event: dict, x_user: Optional[str] = None) -> Any:
        headers = {"X-User": x_user} if x_user else None
        return self._request(
            "POST",
            f"/api/changesets/{changeset_id}/events",
            json_body={"event": event},
            headers=headers,
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
        headers = {"X-User": x_user} if x_user else None
        return self._request(
            "POST",
            f"/api/changesets/{changeset_id}/publish",
            headers=headers,
        )

    # --- Editor ---
    def get_snap_targets(self, bbox: str) -> Any:
        return self.get("/api/snap-targets", params={"bbox": bbox})

    # --- Health ---
    def health(self) -> Any:
        return self.get("/health")


def _json_result(obj: Any) -> str:
    """Serialize result for MCP tool response; if it's an error dict, return readable message."""
    if isinstance(obj, dict) and "error" in obj:
        return json.dumps(obj, ensure_ascii=False)
    return json.dumps(obj, ensure_ascii=False, default=str)
