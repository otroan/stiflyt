import type {
  AreaRouteSummaryResponse,
  AreaStatsResponse,
  CandidatesResponse,
  FieldPhoto,
  FieldPhotosResponse,
  PlacenameCandidatesResponse,
} from "./types";

const BASE = "/api/v1";

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", "X-User": "signs_app" },
    ...init,
  });
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
    const res = await fetch(`${BASE}/signs/sites/${signSiteId}`, {
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
      ? await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-User": "signs_app" },
          body: JSON.stringify({ panels }),
        })
      : await fetch(url, { headers: { "X-User": "signs_app" } });
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

  // (getRoutesForArea removed — signs_app now reads route geometries from
  //  the patched /v1/signs/area/{area}/routes endpoint, so errata remaps
  //  reflect on the map.)

  // --- Field photos ---

  listPhotos: (area: string, pending?: boolean) => {
    const q = pending == null ? "" : `&pending=${pending}`;
    return jsonFetch<FieldPhotosResponse>(`/photos?area=${area}${q}`);
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
    const res = await fetch(`${BASE}/photos`, {
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
    const res = await fetch(`${BASE}/photos/${photoId}`, {
      method: "DELETE",
      headers: { "X-User": "signs_app" },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`API ${res.status} delete photo: ${text}`);
    }
  },
};
