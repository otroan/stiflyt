import type {
  AreaRouteSummaryResponse,
  AreaStatsResponse,
  CandidatesResponse,
  FieldPhoto,
  FieldPhotosResponse,
  PlacenameCandidatesResponse,
  SessionUser,
} from "./types";

const BASE = "/api/v1";

// Suppressed once we've already triggered a redirect to the login flow, so a
// burst of in-flight 401s doesn't replace `window.location` repeatedly.
let didRedirectOn401 = false;

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
    headers: { "Content-Type": "application/json", "X-User": "signs_app" },
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
    headers: { "Content-Type": "application/json", "X-User": "signs_app" },
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
      headers: { "X-User": "signs_app" },
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
          headers: { "Content-Type": "application/json", "X-User": "signs_app" },
          body: JSON.stringify({ panels }),
        })
      : await fetchWithAuth(url, { headers: { "X-User": "signs_app" } });
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
          headers: { "Content-Type": "application/json", "X-User": "signs_app" },
          body: JSON.stringify({ panels }),
        })
      : await fetchWithAuth(url, { headers: { "X-User": "signs_app" } });
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
      headers: { "X-User": "signs_app" },
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
      headers: { "X-User": "signs_app" },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status} delete photo: ${text}`);
    }
  },
};
