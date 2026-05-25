import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { CandidatesResponse, FieldPhoto, RouteListItem, RouteSummary, SignSite } from "./types";
import MapView, { type BaseLayerId } from "./MapView";
import SiteEditor from "./SiteEditor";
import AreaReport from "./AreaReport";
import PhotoPanel, { PhotoLightbox } from "./PhotoPanel";

const BASE_LAYER_STORAGE_KEY = "signs_app:baseLayer";
const BASE_LAYER_LABELS: Record<BaseLayerId, string> = {
  osm: "OpenStreetMap",
  topo4: "Topo4 (Kartverket)",
  topo4graatone: "Topo4 gråtone",
};


const DEFAULT_AREA = "bre";

type Mode = "browse" | "add-manual" | "place-photo";

export default function App() {
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
  const [lightboxPhoto, setLightboxPhoto] = useState<FieldPhoto | null>(null);

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
  useEffect(() => { refreshPhotos(); }, [areaCode]);
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
  }, [areaCode]);

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

  function openLightbox(photo: FieldPhoto) { setLightboxPhoto(photo); }
  async function handlePhotoMarkerClick(photoId: number) {
    const p = photos.find((x) => x.id === photoId);
    if (p) setLightboxPhoto(p);
  }

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
        <button disabled title="Felt-PDF — kommer">Felt-PDF</button>
        <button
          onClick={() => setPhotosVisible((v) => !v)}
          title={photosVisible ? "Skjul bilder på kartet" : "Vis bilder på kartet"}
          style={photosVisible ? {} : { opacity: 0.5 }}
        >
          {photosVisible ? "📷 På" : "📷 Av"}
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
            photos={placedPhotos}
            photosVisible={photosVisible}
            onPhotoClick={handlePhotoMarkerClick}
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

      {lightboxPhoto && (
        <PhotoLightbox
          photo={lightboxPhoto}
          onClose={() => setLightboxPhoto(null)}
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
