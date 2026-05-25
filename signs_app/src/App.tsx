import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { CandidatesResponse, FieldPhoto, RouteListItem, RouteSummary, SessionUser, SignSite } from "./types";
import MapView, { type BaseLayerId } from "./MapView";
import SiteEditor from "./SiteEditor";
import AreaReport from "./AreaReport";
import PhotoPanel, { PhotoLightbox } from "./PhotoPanel";

const LOGIN_ERROR_MESSAGES: Record<string, string> = {
  not_allowed: "E-postadressen din står ikke i tilgangslisten. Kontakt en administrator.",
  email_unverified: "Google-kontoen din har ikke verifisert e-postadressen.",
  oauth_error: "Innloggingen ble avbrutt eller feilet. Prøv igjen.",
};

function LoginScreen({ errorCode }: { errorCode: string | null }) {
  const msg = errorCode ? LOGIN_ERROR_MESSAGES[errorCode] ?? `Feil: ${errorCode}` : null;
  return (
    <div className="login-screen">
      <div className="login-card">
        <h1>Skiltverktøy</h1>
        <p>Logg inn med Google-kontoen din for å fortsette.</p>
        {msg && <div className="login-error">{msg}</div>}
        <a className="login-btn" href="/api/v1/auth/login">Logg inn med Google</a>
      </div>
    </div>
  );
}

const BASE_LAYER_STORAGE_KEY = "signs_app:baseLayer";
const BASE_LAYER_LABELS: Record<BaseLayerId, string> = {
  osm: "OpenStreetMap",
  topo4: "Topo4 (Kartverket)",
  topo4graatone: "Topo4 gråtone",
};


const DEFAULT_AREA = "bre";

type Mode = "browse" | "add-manual" | "place-photo";

export default function App() {
  // Auth state. `me` is null until we've checked; once set we render the
  // real app. If /me 401s, api.ts triggers the redirect and we render the
  // login screen as a brief flash (or longer if login_error is in the URL).
  const [me, setMe] = useState<SessionUser | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [loginErrorCode, setLoginErrorCode] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("login_error");
  });
  useEffect(() => {
    let cancelled = false;
    api.getMe()
      .then((u) => { if (!cancelled) setMe(u); })
      .catch(() => { /* network / 5xx — leave login screen up so user can retry */ })
      .finally(() => { if (!cancelled) setAuthChecking(false); });
    return () => { cancelled = true; };
  }, []);

  // Strip ?login_error= from the URL once the user is in (or even just
  // checking) so a manual refresh doesn't re-display the error.
  useEffect(() => {
    if (loginErrorCode && me) {
      const u = new URL(window.location.href);
      u.searchParams.delete("login_error");
      window.history.replaceState({}, "", u.toString());
      setLoginErrorCode(null);
    }
  }, [me, loginErrorCode]);

  const [areaCode, setAreaCode] = useState<string>(DEFAULT_AREA);
  const [candidates, setCandidates] = useState<CandidatesResponse | null>(null);
  const [routes, setRoutes] = useState<RouteListItem[]>([]);
  const [routeSummaries, setRouteSummaries] = useState<Map<string, RouteSummary>>(new Map());
  // Track the selected site by stable key (sign_site_id or anchor_node_id) so
  // it survives reorderings of the candidates list (which can happen on any
  // refresh — manual sites are appended after anchor sites and may shuffle
  // when rows are added/removed). selectedSiteIdx (the *array position*) is
  // recomputed from the key whenever candidates change.
  const [selectedSiteKey, setSelectedSiteKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("browse");
  const [baseLayer, setBaseLayer] = useState<BaseLayerId>(() => {
    const stored = localStorage.getItem(BASE_LAYER_STORAGE_KEY);
    return stored === "topo4" || stored === "topo4graatone" ? stored : "osm";
  });
  useEffect(() => { localStorage.setItem(BASE_LAYER_STORAGE_KEY, baseLayer); }, [baseLayer]);
  const [focusedRoute, setFocusedRoute] = useState<string | null>(null);
  const [showReport, setShowReport] = useState(false);

  // --- Field photos state ---
  const [photos, setPhotos] = useState<FieldPhoto[]>([]);
  const [photosOpen, setPhotosOpen] = useState(false);
  const [photosVisible, setPhotosVisible] = useState(true);
  // Photo from the pending-placement tray that's been picked. The next map
  // click in "place-photo" mode geotags this photo at the clicked position.
  const [pendingPlacementId, setPendingPlacementId] = useState<number | null>(null);
  // Lightbox holds a *set* of photos so the user can page through them with
  // ←/→. Single-photo opens just pass a one-element list.
  const [lightboxState, setLightboxState] = useState<{ photos: FieldPhoto[]; index: number } | null>(null);

  const placedPhotos = useMemo(() => photos.filter((p) => p.lon != null && p.lat != null), [photos]);
  const pendingPhotos = useMemo(() => photos.filter((p) => p.needs_placement), [photos]);

  const refreshPhotos = async () => {
    try {
      const r = await api.listPhotos(areaCode);
      setPhotos(r.photos);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  };
  useEffect(() => { if (me) refreshPhotos(); }, [areaCode, me]);
  // Set of "<sign_site_id>:<destination_anchor_node_id>" strings — panels the
  // user has earmarked for the next manufacturing export.
  const [selectedPanels, setSelectedPanels] = useState<Set<string>>(new Set());
  const togglePanelSelection = (key: string) =>
    setSelectedPanels((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  const clearPanelSelection = () => setSelectedPanels(new Set());

  useEffect(() => {
    if (!me) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelectedSiteKey(null);
    Promise.all([
      api.getCandidates(areaCode),
      // The signs_app pulls route geometries from the area-routes summary
      // (which goes through ops.fotruteinfo_patched), not the legacy
      // /v1/routes endpoint. This keeps the rendered map line in sync with
      // any rutenummer remap from data/route_errata.yaml.
      api.getAreaRoutes(areaCode),
    ])
      .then(([c, summary]) => {
        if (cancelled) return;
        setCandidates(c);
        const m = new Map<string, RouteSummary>();
        const routeItems: RouteListItem[] = [];
        for (const s of summary.routes || []) {
          m.set(s.rutenummer, s);
          if (s.route_geometry) {
            routeItems.push({
              rutenummer: s.rutenummer,
              rutenavn: s.rutenavn ?? null,
              route_geometry: s.route_geometry,
            });
          }
        }
        setRoutes(routeItems);
        setRouteSummaries(m);
      })
      .catch((e) => !cancelled && setError(String(e?.message || e)))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [areaCode, me]);

  const refreshCandidates = async (): Promise<CandidatesResponse | null> => {
    try {
      const c = await api.getCandidates(areaCode);
      setCandidates(c);
      return c;
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
      return null;
    }
  };

  function siteKey(s: SignSite): string {
    // Stable identifier for selection. Accepted sites have a sign_site_id;
    // proposed anchor candidates use the anchor_node_id (prefixed so it
    // doesn't collide with sign_site_id integers).
    if (s.sign_site_id != null) return `s:${s.sign_site_id}`;
    if (s.anchor_node_id != null) return `a:${s.anchor_node_id}`;
    return "?";
  }

  const selectedSite: SignSite | null = useMemo(() => {
    if (!candidates || selectedSiteKey == null) return null;
    return candidates.sites.find((s) => siteKey(s) === selectedSiteKey) ?? null;
  }, [candidates, selectedSiteKey]);

  const selectedSiteIdx: number | null = useMemo(() => {
    if (!candidates || selectedSiteKey == null) return null;
    const idx = candidates.sites.findIndex((s) => siteKey(s) === selectedSiteKey);
    return idx >= 0 ? idx : null;
  }, [candidates, selectedSiteKey]);

  const selectSiteByIdx = (idx: number | null) => {
    if (idx == null || !candidates) { setSelectedSiteKey(null); return; }
    const s = candidates.sites[idx];
    if (s) setSelectedSiteKey(siteKey(s));
  };

  // Fallback for clicks that didn't land directly on a rendered route line.
  const routeFeatures = useMemo(() => {
    return routes
      .filter((r) => r.route_geometry && r.rutenummer)
      .map((r) => ({ rutenummer: r.rutenummer, geometry: r.route_geometry as GeoJSON.Geometry }));
  }, [routes]);

  async function handleMapClick(lon: number, lat: number, routesAtPoint: string[]) {
    if (mode === "place-photo") {
      // Geotag the picked-pending photo at the clicked position, then exit.
      if (pendingPlacementId == null) { setMode("browse"); return; }
      try {
        await api.patchPhoto(pendingPlacementId, { lon, lat });
        setPendingPlacementId(null);
        setMode("browse");
        await refreshPhotos();
      } catch (e) {
        setError(String((e as Error)?.message ?? e));
      }
      return;
    }
    if (mode !== "add-manual") return;
    // Prefer the routes MapLibre rendered under the cursor (handles shared
    // segments correctly). If the click just missed every line, fall back to
    // the nearest route by raw point-to-segment distance.
    let routes = routesAtPoint;
    if (routes.length === 0) {
      const nearest = nearestRoute(routeFeatures, lon, lat);
      if (!nearest) { setError("Fant ingen rute nær klikket"); return; }
      routes = [nearest.rutenummer];
    }
    // A sign on a shared segment belongs to every route that crosses there;
    // no picker — just confirm with the user-readable route list.
    await placeManualSign(lon, lat, routes);
  }

  function pickPendingForPlacement(photoId: number | null) {
    setPendingPlacementId(photoId);
    setMode(photoId == null ? "browse" : "place-photo");
  }

  function openLightbox(set: FieldPhoto[], initial: FieldPhoto) {
    const idx = Math.max(0, set.findIndex((p) => p.id === initial.id));
    setLightboxState({ photos: set, index: idx });
  }
  function handleMapPhotosOpen(ids: number[]) {
    // Map order to the user's click intent — single dot passes one id, a
    // cluster passes every photo inside it. Preserve the order ids came in.
    const byId = new Map(photos.map((p) => [p.id, p] as const));
    const set = ids.map((id) => byId.get(id)).filter((p): p is FieldPhoto => !!p);
    if (set.length === 0) return;
    setLightboxState({ photos: set, index: 0 });
  }
  // Keep the lightbox's set in sync with refreshed photo data (e.g. after
  // editing a caption, the parent's `photos` list updates and we want the
  // open lightbox to reflect the new caption/tags too).
  useEffect(() => {
    if (!lightboxState) return;
    const byId = new Map(photos.map((p) => [p.id, p] as const));
    const refreshed = lightboxState.photos
      .map((p) => byId.get(p.id))
      .filter((p): p is FieldPhoto => !!p);
    if (refreshed.length === 0) { setLightboxState(null); return; }
    // Only update if something actually changed by reference — guards against
    // an infinite render loop.
    const same = refreshed.length === lightboxState.photos.length
      && refreshed.every((p, i) => p === lightboxState.photos[i]);
    if (same) return;
    const currentId = lightboxState.photos[lightboxState.index]?.id;
    const newIndex = Math.max(0, refreshed.findIndex((p) => p.id === currentId));
    setLightboxState({ photos: refreshed, index: newIndex });
  }, [photos]);

  async function placeManualSign(lon: number, lat: number, routes: string[]) {
    if (routes.length === 0) return;
    try {
      // Create the sign with no name first — the user names it via the
      // NamePicker in the side panel, which already does the stedsnavn +
      // ruteinfopunkt lookup we want here.
      const created = await api.createManualSign(areaCode, {
        rutenummer_list: routes,
        lon,
        lat,
        name: null,
      });
      const fresh = await refreshCandidates();
      setMode("browse");
      // Auto-select the new site so the user immediately sees it in the side
      // panel (and the map zooms to it). This fixes the "nothing visibly
      // happened after I placed it" confusion.
      if (fresh) {
        setSelectedSiteKey(`s:${created.id}`);
      }
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }
  }

  if (authChecking) {
    return <div className="app-booting">Sjekker innlogging…</div>;
  }
  if (!me) {
    return <LoginScreen errorCode={loginErrorCode} />;
  }

  return (
    <div className="app">
      <div className="topbar">
        <span>Skiltverktøy —</span>
        <select value={areaCode} onChange={(e) => setAreaCode(e.target.value)}>
          <option value="bre">Breheimen og Jostedalsbreen</option>
        </select>
        <div className="spacer" />
        <span className="stat">
          {candidates
            ? `${candidates.totals.total_sites} steder · ${candidates.totals.accepted} aksept · ${candidates.totals.rejected ?? 0} avvist`
            : loading
              ? "Laster…"
              : ""}
        </span>
        <select
          value={baseLayer}
          onChange={(e) => setBaseLayer(e.target.value as BaseLayerId)}
          title="Bakgrunnskart"
        >
          {(Object.keys(BASE_LAYER_LABELS) as BaseLayerId[]).map((k) => (
            <option key={k} value={k}>{BASE_LAYER_LABELS[k]}</option>
          ))}
        </select>
        {focusedRoute && (
          <button
            onClick={() => setFocusedRoute(null)}
            title="Fjern fokus"
            style={{ background: "#1a7fc4", color: "white", borderColor: "#1a7fc4" }}
          >
            ✕ Fokus: {focusedRoute}
          </button>
        )}
        <button
          onClick={() => setMode((m) => (m === "add-manual" ? "browse" : "add-manual"))}
          style={mode === "add-manual" ? { background: "#fae3a8" } : {}}
          title="Plassér et manuelt skilt — klikk på en rute"
        >
          {mode === "add-manual" ? "Klikk på kartet…" : "+ Manuelt skilt"}
        </button>
        <button
          onClick={() => api.downloadManufacturingXlsx(areaCode).catch((e) => setError(String((e as Error)?.message ?? e)))}
          title="Last ned hele skiltlisten som Excel"
        >
          Excel (alle)
        </button>
        <button
          onClick={() => api.downloadManufacturingXlsx(areaCode, Array.from(selectedPanels))
            .catch((e) => setError(String((e as Error)?.message ?? e)))}
          disabled={selectedPanels.size === 0}
          title={selectedPanels.size === 0 ? "Velg panel(er) for å eksportere et utvalg" : `Last ned ${selectedPanels.size} valgte panel`}
        >
          Excel ({selectedPanels.size} valgt)
        </button>
        {selectedPanels.size > 0 && (
          <button onClick={clearPanelSelection} title="Tøm utvalget">Tøm</button>
        )}
        <button
          onClick={() => api.downloadFieldPdf(areaCode).catch((e) => setError(String((e as Error)?.message ?? e)))}
          title="Felt-PDF — ett oppslag per skiltsted (kartutsnitt, paneler, bilder)"
        >
          Felt-PDF (alle)
        </button>
        <button
          onClick={() => api.downloadFieldPdf(areaCode, Array.from(selectedPanels))
            .catch((e) => setError(String((e as Error)?.message ?? e)))}
          disabled={selectedPanels.size === 0}
          title={selectedPanels.size === 0 ? "Velg panel(er) for å eksportere et utvalg" : `Felt-PDF for ${selectedPanels.size} valgte panel`}
        >
          Felt-PDF ({selectedPanels.size} valgt)
        </button>
        <button
          onClick={() => setPhotosOpen((v) => !v)}
          style={photosOpen ? { background: "#eaf3fc" } : {}}
          title="Åpne bildepanelet"
        >
          Bilder ({photos.length}{pendingPhotos.length > 0 ? `, ${pendingPhotos.length} venter` : ""})
        </button>
        <button
          onClick={() => setShowReport(true)}
          title="Om området — totalt antall ruter, lengde, skiltsteder og paneler"
        >
          ℹ Om området
        </button>
        <div className="user-widget" title={me.email}>
          {me.picture && <img src={me.picture} alt="" className="user-avatar" />}
          <span className="user-email">{me.email}</span>
          <button
            onClick={() => api.logout().catch((e) => setError(String((e as Error)?.message ?? e)))}
            title="Logg ut"
          >
            Logg ut
          </button>
        </div>
      </div>

      <div className="map-pane">
        {error && <div className="empty">Feil: {error}</div>}
        {!error && (
          <MapView
            routes={routes}
            routeSummaries={routeSummaries}
            sites={candidates?.sites ?? []}
            selectedIdx={selectedSiteIdx}
            onSelect={selectSiteByIdx}
            onMapClick={(mode === "add-manual" || mode === "place-photo") ? handleMapClick : undefined}
            cursor={(mode === "add-manual" || mode === "place-photo") ? "crosshair" : undefined}
            baseLayer={baseLayer}
            focusedRoute={focusedRoute}
            onFocusRoute={setFocusedRoute}
            areaCode={areaCode}
            photos={placedPhotos}
            photosVisible={photosVisible}
            onPhotosVisibleChange={setPhotosVisible}
            onPhotosOpen={handleMapPhotosOpen}
          />
        )}
      </div>

      <div className="side">
        {photosOpen ? (
          <PhotoPanel
            areaCode={areaCode}
            placed={placedPhotos}
            pending={pendingPhotos}
            selectedPendingId={pendingPlacementId}
            placementArmed={mode === "place-photo"}
            onPickPendingForPlacement={pickPendingForPlacement}
            onClose={() => setPhotosOpen(false)}
            onChanged={refreshPhotos}
            onOpenLightbox={openLightbox}
          />
        ) : (
          <>
            {!selectedSite && (
              <div className="empty">
                {mode === "add-manual"
                  ? "Klikk på kartet langs en rute for å plassere et manuelt skilt. Felles segment blir automatisk knyttet til alle rutene der."
                  : mode === "place-photo"
                    ? "Klikk på kartet for å plassere det valgte bildet."
                    : loading
                      ? "Laster skiltsteder…"
                      : "Velg et skiltsted på kartet."}
              </div>
            )}
            {selectedSite && (
              <SiteEditor
                site={selectedSite}
                areaCode={areaCode}
                onClose={() => setSelectedSiteKey(null)}
                onChanged={refreshCandidates}
                selectedPanels={selectedPanels}
                onTogglePanel={togglePanelSelection}
              />
            )}
          </>
        )}
      </div>

      {showReport && (
        <AreaReport
          areaCode={areaCode}
          candidates={candidates}
          routeSummaries={routeSummaries}
          onClose={() => setShowReport(false)}
        />
      )}

      {lightboxState && (
        <PhotoLightbox
          photos={lightboxState.photos}
          initialIndex={lightboxState.index}
          onClose={() => setLightboxState(null)}
          onChanged={refreshPhotos}
        />
      )}
    </div>
  );
}

interface RouteFeature {
  rutenummer: string;
  geometry: GeoJSON.Geometry;
}

function nearestRoute(features: RouteFeature[], lon: number, lat: number): RouteFeature | null {
  let best: { f: RouteFeature; d: number } | null = null;
  for (const f of features) {
    const d = minDistanceToGeometry(f.geometry, lon, lat);
    if (d == null) continue;
    if (best == null || d < best.d) best = { f, d };
  }
  return best?.f ?? null;
}

function minDistanceToGeometry(geom: GeoJSON.Geometry, lon: number, lat: number): number | null {
  // Squared planar approximation in degrees — fine for picking the *closest* route within a small area.
  if (geom.type === "LineString") return minDistanceToLine(geom.coordinates as [number, number][], lon, lat);
  if (geom.type === "MultiLineString") {
    let best: number | null = null;
    for (const line of geom.coordinates as [number, number][][]) {
      const d = minDistanceToLine(line, lon, lat);
      if (d != null && (best == null || d < best)) best = d;
    }
    return best;
  }
  return null;
}

function minDistanceToLine(line: [number, number][], lon: number, lat: number): number | null {
  if (!line || line.length < 2) return null;
  let best = Infinity;
  for (let i = 1; i < line.length; i++) {
    const d = pointToSegment(lon, lat, line[i - 1][0], line[i - 1][1], line[i][0], line[i][1]);
    if (d < best) best = d;
  }
  return best;
}

function pointToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return (px - ax) ** 2 + (py - ay) ** 2;
  let t = ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx, cy = ay + t * dy;
  return (px - cx) ** 2 + (py - cy) ** 2;
}
