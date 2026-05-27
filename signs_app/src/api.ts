import type {
  AreaRouteSummaryResponse,
  AreaStatsResponse,
  CandidatesResponse,
  FieldPhoto,
  FieldPhotosResponse,
  PlacenameCandidatesResponse,
  LinkBridgesResponse,
  LinkExclusionsResponse,
  RouteAnnotation,
  RouteAnnotationsResponse,
  RouteValidationResponse,
  SessionUser,
  WorkMarkersResponse,
} from "./types";

const BASE = "/api/v1";

// Suppressed once we've already triggered a redirect to the login flow, so a
// burst of in-flight 401s doesn't replace `window.location` repeatedly.
let didRedirectOn401 = false;

// Authenticated user's email. The backend's mutation endpoints read it from
// the `X-User` header (see api/routes.py:2276) and persist it as
// `recorded_by` / `updated_by` / `uploaded_by`. App.tsx calls `setCurrentUser`
// after the /auth/me round-trip; until then we send "signs_app" so the
// header is always non-empty and server-side validation never breaks.
let currentUserEmail: string | null = null;
function xUser(): string {
  return currentUserEmail || "signs_app";
}

class UnauthenticatedError extends Error {
  constructor() {
    super("not_authenticated");
    this.name = "UnauthenticatedError";
  }
}

function handleMaybeAuth(res: Response): void {
  if (res.status !== 401) return;
  if (!didRedirectOn401) {
    didRedirectOn401 = true;
    // Send the user back to the app root (respecting the Vite `base`) after
    // login by stashing it in the OAuth `next` param. The backend reads it
    // and redirects there post-callback (defaults to `/` otherwise).
    const next = encodeURIComponent(import.meta.env.BASE_URL);
    window.location.href = `/api/v1/auth/login?next=${next}`;
  }
  throw new UnauthenticatedError();
}

/** fetch() that auto-redirects to login on 401. Use instead of bare `fetch`
 *  whenever calling /api/v1/* directly (i.e. not via jsonFetch). */
async function fetchWithAuth(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const res = await fetch(input, init);
  handleMaybeAuth(res);
  return res;
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", "X-User": xUser() },
    ...init,
  });
  handleMaybeAuth(res);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status} ${path}: ${text}`);
  }
  return res.json();
}

// Same as jsonFetch but logs (network, parse, Server-Timing) — used for the
// two heavyweight endpoints so the breakdown shows up in the browser console
// alongside DevTools' native Server-Timing rendering.
async function timedJsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const t0 = performance.now();
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", "X-User": xUser() },
    ...init,
  });
  const tNet = performance.now() - t0;
  handleMaybeAuth(res);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status} ${path}: ${text}`);
  }
  const tParse0 = performance.now();
  const body = (await res.json()) as T;
  const tParse = performance.now() - tParse0;
  const serverTiming = res.headers.get("Server-Timing");
  // eslint-disable-next-line no-console
  console.log(
    `[timing] ${path}  net=${tNet.toFixed(0)}ms  parse=${tParse.toFixed(0)}ms`
      + (serverTiming ? `  server={${serverTiming}}` : ""),
  );
  return body;
}

export const api = {
  /** Set after successful /auth/me so subsequent writes carry the user's
   *  identity in the X-User header (which the backend persists as
   *  recorded_by / updated_by / uploaded_by). Null clears it. */
  setCurrentUser: (email: string | null) => { currentUserEmail = email; },

  /** Current session user, or null if not logged in. Does NOT redirect — the
   *  caller decides whether to show a login screen or bounce to Google. */
  getMe: async (): Promise<SessionUser | null> => {
    const res = await fetch(`${BASE}/auth/me`, {
      headers: { "Content-Type": "application/json" },
    });
    if (res.status === 401) return null;
    if (!res.ok) throw new Error(`API ${res.status} /auth/me`);
    return res.json();
  },

  logout: async () => {
    const res = await fetch(`${BASE}/auth/logout`, { method: "POST" });
    if (!res.ok) throw new Error(`API ${res.status} logout`);
    // Clear the redirect guard and bounce to /; the next /me will 401 and
    // restart the login flow.
    didRedirectOn401 = false;
    window.location.href = import.meta.env.BASE_URL;
  },

  getCandidates: (area: string) => timedJsonFetch<CandidatesResponse>(`/signs/candidates/${area}`),

  getAreaRoutes: (area: string) => timedJsonFetch<AreaRouteSummaryResponse>(`/signs/area/${area}/routes`),

  getAreaStats: (area: string) => jsonFetch<AreaStatsResponse>(`/signs/area/${area}/stats`),

  acceptCandidate: (area: string, anchorNodeId: number) =>
    jsonFetch<{ id: number; site_code: string | null; status: string }>(
      `/signs/candidates/${area}/anchors/${anchorNodeId}/accept`,
      { method: "POST", body: "{}" },
    ),

  rejectCandidate: (area: string, anchorNodeId: number) =>
    jsonFetch<{ id: number; status: string }>(
      `/signs/candidates/${area}/anchors/${anchorNodeId}/reject`,
      { method: "POST", body: "{}" },
    ),

  setAnchorName: (anchorId: number, name: string) =>
    jsonFetch<{ anchor_node_id: number; name: string }>(`/signs/anchors/${anchorId}/name`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  getAnchorPlacenames: (anchorId: number, radius = 500, limit = 12) =>
    jsonFetch<PlacenameCandidatesResponse>(
      `/anchors/${anchorId}/placenames?radius=${radius}&limit=${limit}`,
    ),

  getPlacenamesNearby: (lon: number, lat: number, radius = 500, limit = 12) =>
    jsonFetch<PlacenameCandidatesResponse>(
      `/signs/placenames?lon=${lon}&lat=${lat}&radius=${radius}&limit=${limit}`,
    ),

  updateSiteName: (signSiteId: number, name: string) =>
    jsonFetch<unknown>(`/signs/sites/${signSiteId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  patchPanel: (
    signSiteId: number,
    destinationAnchorNodeId: number,
    payload: {
      color?: "trehvit" | "grønn";
      direction?: string | null;
      distance_km?: number | null;
      destination_name?: string | null;
      /** first_link_id discriminates panels that share (sign_site_id, anchor_node_id)
       *  but are parallel-path siblings (e.g. bre21 vs bre62 to Arentzbu).
       *  Always include the panel's first_link_id so the storage key picks
       *  the right row instead of overwriting its sibling. */
      first_link_id?: number | null;
    },
  ) =>
    jsonFetch<unknown>(
      `/signs/sites/${signSiteId}/panels/${destinationAnchorNodeId}/edit`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),

  createManualSign: (
    area: string,
    payload: { rutenummer_list: string[]; lon: number; lat: number; name?: string | null },
  ) =>
    jsonFetch<{
      id: number;
      site_code: string;
      rutenummer: string;
      rutenummer_list: string[];
      route_km: number;
      name: string | null;
    }>(`/signs/candidates/${area}/manual`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  deleteSite: async (signSiteId: number) => {
    const res = await fetchWithAuth(`${BASE}/signs/sites/${signSiteId}`, {
      method: "DELETE",
      headers: { "X-User": xUser() },
    });
    if (!res.ok && res.status !== 204) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status} delete site ${signSiteId}: ${text}`);
    }
  },

  downloadManufacturingXlsx: async (area: string, panels?: string[]) => {
    // GET when no selection — keeps the simple "click to download" URL flow.
    // POST when there's a selection — body avoids URL-length limits.
    const url = `${BASE}/signs/manufacturing/${area}.xlsx`;
    const res = panels && panels.length > 0
      ? await fetchWithAuth(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-User": xUser() },
          body: JSON.stringify({ panels }),
        })
      : await fetchWithAuth(url, { headers: { "X-User": xUser() } });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status} xlsx: ${text}`);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `skilt-${area}${panels && panels.length > 0 ? "-valgte" : ""}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 30_000);
  },

  /** Field-PDF: one A4 page per sign site with map snippet, photos, panels. */
  downloadFieldPdf: async (area: string, panels?: string[]) => {
    const url = `${BASE}/signs/field-pdf/${area}.pdf`;
    const res = panels && panels.length > 0
      ? await fetchWithAuth(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-User": xUser() },
          body: JSON.stringify({ panels }),
        })
      : await fetchWithAuth(url, { headers: { "X-User": xUser() } });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status} field-pdf: ${text}`);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `feltkart-${area}${panels && panels.length > 0 ? "-valgte" : ""}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 30_000);
  },

  // --- Route annotations (rutebok / inspeksjon / dugnad / arbeid) ---

  listRouteAnnotations: (area: string, rutenummer: string, opts?: { kind?: string; includeResolved?: boolean }) => {
    const params = new URLSearchParams();
    if (opts?.kind) params.set("kind", opts.kind);
    if (opts?.includeResolved === false) params.set("include_resolved", "false");
    const q = params.toString();
    return jsonFetch<RouteAnnotationsResponse>(
      `/routes/${area}/${encodeURIComponent(rutenummer)}/annotations${q ? `?${q}` : ""}`,
    );
  },

  createRouteAnnotation: (area: string, rutenummer: string, payload: {
    kind: string;
    title?: string | null;
    body?: string | null;
    occurred_at?: string | null;
    position_along_m?: number | null;
    lon?: number | null;
    lat?: number | null;
  }) =>
    jsonFetch<RouteAnnotation>(
      `/routes/${area}/${encodeURIComponent(rutenummer)}/annotations`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  updateRouteAnnotation: (id: number, patch: Partial<RouteAnnotation> & { lon?: number | null; lat?: number | null }) =>
    jsonFetch<RouteAnnotation>(`/route-annotations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteRouteAnnotation: async (id: number) => {
    const res = await fetchWithAuth(`${BASE}/route-annotations/${id}`, {
      method: "DELETE",
      headers: { "X-User": xUser() },
    });
    if (!res.ok && res.status !== 204) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status} delete annotation: ${text}`);
    }
  },

  listWorkMarkers: (area: string, includeResolved = false) =>
    jsonFetch<WorkMarkersResponse>(
      `/routes/${area}/work-markers${includeResolved ? "?include_resolved=true" : ""}`,
    ),

  // --- Route validation + link-exclusion correction ---

  getRouteValidation: (area: string, rutenummer: string) =>
    jsonFetch<RouteValidationResponse>(
      `/routes/${area}/${encodeURIComponent(rutenummer)}/validation`,
    ),

  listLinkExclusions: (area: string, rutenummer: string) =>
    jsonFetch<LinkExclusionsResponse>(
      `/routes/${area}/${encodeURIComponent(rutenummer)}/link-exclusions`,
    ),

  addLinkExclusions: (
    area: string,
    rutenummer: string,
    payload: { link_ids: number[]; reason?: string; comment?: string },
  ) =>
    jsonFetch<LinkExclusionsResponse>(
      `/routes/${area}/${encodeURIComponent(rutenummer)}/link-exclusions`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  clearLinkExclusions: (area: string, rutenummer: string, linkIds?: number[]) => {
    const q = linkIds && linkIds.length > 0 ? `?link_ids=${linkIds.join(",")}` : "";
    return jsonFetch<{ area_code: string; rutenummer: string; deleted: number }>(
      `/routes/${area}/${encodeURIComponent(rutenummer)}/link-exclusions${q}`,
      { method: "DELETE" },
    );
  },

  listLinkBridges: (area: string, rutenummer: string) =>
    jsonFetch<LinkBridgesResponse>(
      `/routes/${area}/${encodeURIComponent(rutenummer)}/link-bridges`,
    ),

  addLinkBridge: (
    area: string,
    rutenummer: string,
    payload: { a_node: number; b_node: number; reason?: string; comment?: string },
  ) =>
    jsonFetch<LinkBridgesResponse>(
      `/routes/${area}/${encodeURIComponent(rutenummer)}/link-bridges`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  clearLinkBridges: (area: string, rutenummer: string, nodePair?: [number, number]) => {
    const q = nodePair ? `?nodes=${nodePair[0]}-${nodePair[1]}` : "";
    return jsonFetch<{ area_code: string; rutenummer: string; deleted: number }>(
      `/routes/${area}/${encodeURIComponent(rutenummer)}/link-bridges${q}`,
      { method: "DELETE" },
    );
  },

  /** Route-validation XLSX: one row per issue + a per-route summary sheet. */
  downloadValidationXlsx: async (area: string) => {
    const url = `${BASE}/signs/validation/${area}.xlsx`;
    const res = await fetchWithAuth(url, { headers: { "X-User": xUser() } });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status} validation-xlsx: ${text}`);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `rutevalidering-${area}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 30_000);
  },

  // (getRoutesForArea removed — signs_app now reads route geometries from
  //  the patched /v1/signs/area/{area}/routes endpoint, so errata remaps
  //  reflect on the map.)

  // --- Field photos ---

  listPhotos: (area: string, pending?: boolean) => {
    const q = pending == null ? "" : `&pending=${pending}`;
    return jsonFetch<FieldPhotosResponse>(`/photos?area=${area}${q}`);
  },

  /** Bulk-fetch base64 thumbnail bytes for every placed photo in the area
   *  (optionally clipped to a viewport bbox). One request returns all thumbs
   *  in one go — the map registers them as map images and the cluster /
   *  single-photo layers light up immediately. */
  getPhotoThumbnails: (
    area: string,
    bbox?: { minLng: number; minLat: number; maxLng: number; maxLat: number },
  ) => {
    const q = bbox
      ? `&bbox=${bbox.minLng},${bbox.minLat},${bbox.maxLng},${bbox.maxLat}`
      : "";
    return jsonFetch<{
      area_code: string;
      thumbs: { id: number; data: string }[];
      count: number;
    }>(`/photos/thumbnails?area=${area}${q}`);
  },

  uploadPhoto: async (
    area: string,
    file: File,
    payload?: { caption?: string; tags?: string[] },
  ): Promise<FieldPhoto> => {
    const form = new FormData();
    form.append("area", area);
    form.append("file", file);
    if (payload?.caption) form.append("caption", payload.caption);
    for (const t of payload?.tags ?? []) form.append("tags", t);
    const res = await fetchWithAuth(`${BASE}/photos`, {
      method: "POST",
      headers: { "X-User": xUser() },
      body: form,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status} upload: ${text}`);
    }
    return res.json();
  },

  patchPhoto: (
    photoId: number,
    payload: { lon?: number; lat?: number; caption?: string | null; tags?: string[] },
  ) =>
    jsonFetch<FieldPhoto>(`/photos/${photoId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  deletePhoto: async (photoId: number) => {
    const res = await fetchWithAuth(`${BASE}/photos/${photoId}`, {
      method: "DELETE",
      headers: { "X-User": xUser() },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status} delete photo: ${text}`);
    }
  },
};
