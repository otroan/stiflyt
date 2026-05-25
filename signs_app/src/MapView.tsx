import { useEffect, useMemo, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { FieldPhoto, RouteListItem, RouteSummary, SignSite } from "./types";

export type BaseLayerId = "osm" | "topo4" | "topo4graatone";

interface Props {
  routes: RouteListItem[];
  /** rutenummer -> endpoints + total length, populated from /v1/signs/area/{area}/routes. */
  routeSummaries: Map<string, RouteSummary>;
  sites: SignSite[];
  selectedIdx: number | null;
  onSelect: (idx: number | null) => void;
  /** Called for plain-map clicks (not on a marker). lon, lat, and the list of
   *  rutenumre under the click point. Caller can pick one or prompt the user. */
  onMapClick?: (lon: number, lat: number, routesAtPoint: string[]) => void;
  cursor?: string;
  baseLayer: BaseLayerId;
  /** Rutenummer that's persistently "focused": highlighted while every other
   *  route fades. Null = no focus. */
  focusedRoute: string | null;
  onFocusRoute: (rutenummer: string | null) => void;
  /** Placed (geotagged) field photos to render as small thumbnail markers. */
  photos?: FieldPhoto[];
  onPhotoClick?: (photoId: number) => void;
  /** Hide the photo layer when false (toggle in topbar). */
  photosVisible?: boolean;
}

const BREHEIMEN_CENTER: [number, number] = [7.5, 61.7];

// Kartverket's open WMTS cache. {z}/{y}/{x} maps directly to
// {TileMatrix}/{TileRow}/{TileCol}. No auth, attribution required.
const KARTVERKET_TILES = (layer: "topo" | "topograatone") =>
  `https://cache.kartverket.no/v1/wmts/1.0.0/${layer}/default/webmercator/{z}/{y}/{x}.png`;

const BASE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution: "© OpenStreetMap-bidragsytere",
    },
    topo4: {
      type: "raster",
      tiles: [KARTVERKET_TILES("topo")],
      tileSize: 256,
      maxzoom: 18,
      attribution: "© Kartverket",
    },
    topo4graatone: {
      type: "raster",
      tiles: [KARTVERKET_TILES("topograatone")],
      tileSize: 256,
      maxzoom: 18,
      attribution: "© Kartverket",
    },
  },
  layers: [
    // All base layers exist; we flip visibility instead of swapping the source.
    { id: "osm", type: "raster", source: "osm" },
    { id: "topo4", type: "raster", source: "topo4", layout: { visibility: "none" } },
    { id: "topo4graatone", type: "raster", source: "topo4graatone", layout: { visibility: "none" } },
  ],
};

const ALL_BASE_LAYERS: BaseLayerId[] = ["osm", "topo4", "topo4graatone"];

const CLICK_TOLERANCE_PX = 6;

export default function MapView({
  routes,
  routeSummaries,
  sites,
  selectedIdx,
  onSelect,
  onMapClick,
  cursor,
  baseLayer,
  focusedRoute,
  onFocusRoute,
  photos,
  onPhotoClick,
  photosVisible,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  // Single reusable popup; we move/show/hide it instead of creating one per hover.
  const hoverPopupRef = useRef<maplibregl.Popup | null>(null);
  // Stable refs the popup handlers close over — avoids re-binding map events
  // on every focus change.
  const focusedRouteRef = useRef(focusedRoute);
  focusedRouteRef.current = focusedRoute;
  const onFocusRouteRef = useRef(onFocusRoute);
  onFocusRouteRef.current = onFocusRoute;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const routeSummariesRef = useRef(routeSummaries);
  routeSummariesRef.current = routeSummaries;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: BREHEIMEN_CENTER,
      zoom: 9,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({}), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    hoverPopupRef.current = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 8,
      maxWidth: "260px",
    });
    return () => {
      map.remove();
      mapRef.current = null;
      hoverPopupRef.current = null;
    };
  }, []);

  const routesGeoJSON = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: routes
      .filter((r) => r.route_geometry)
      .map((r) => ({
        type: "Feature",
        geometry: r.route_geometry as GeoJSON.Geometry,
        properties: { rutenummer: r.rutenummer, rutenavn: r.rutenavn || "" },
      })),
  }), [routes]);

  const sitesGeoJSON = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: sites
      .filter((s) => s.lon != null && s.lat != null)
      .map((s, idx) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [s.lon!, s.lat!] },
        properties: {
          idx,
          name: s.name || "(uten navn)",
          status: s.status,
          is_endpoint: s.is_endpoint,
          is_junction: s.is_junction,
          is_manual: s.is_manual === true,
          site_code: s.site_code || "",
          route_numbers: s.route_numbers.join(", "),
          n_panels: s.panels.length,
        },
      })),
  }), [sites]);

  // Bootstrap sources + layers + hover/click handlers (run once after map load,
  // then keep data in sync).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const setup = () => {
      // routes source + base line + a hover-highlight line layer that filters
      // to the currently hovered rutenummer.
      if (!map.getSource("routes")) {
        map.addSource("routes", { type: "geojson", data: routesGeoJSON });
        map.addLayer({
          id: "routes-line",
          type: "line",
          source: "routes",
          paint: {
            "line-color": "#c43d3d",
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1.2, 14, 3.5],
            // Opacity controlled by focused-route effect below
            "line-opacity": 0.85,
          },
        });
        map.addLayer({
          id: "routes-line-hover",
          type: "line",
          source: "routes",
          filter: ["==", ["get", "rutenummer"], "__none__"],
          paint: {
            "line-color": "#fac142",
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, 3.5, 14, 7],
            "line-opacity": 0.95,
          },
        });
        map.addLayer({
          id: "routes-line-focused",
          type: "line",
          source: "routes",
          filter: ["==", ["get", "rutenummer"], "__none__"],
          paint: {
            "line-color": "#1a7fc4",
            // Wider than the gold hover layer (3.5–7) so the focused blue is
            // clearly visible when both apply to the same route at once.
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, 5, 14, 10],
            "line-opacity": 1.0,
          },
        });
        attachRouteHoverHandlers(map, hoverPopupRef, focusedRouteRef, onFocusRouteRef, routeSummariesRef);
      } else {
        (map.getSource("routes") as maplibregl.GeoJSONSource).setData(routesGeoJSON);
      }

      // sites source + circle layer + hover popup
      if (!map.getSource("sites")) {
        map.addSource("sites", { type: "geojson", data: sitesGeoJSON });
        map.addLayer({
          id: "sites-circle",
          // (placeholder — see moveLayer call after setup to keep routes-line-focused
          // strictly on top of everything route-related.)
          type: "circle",
          source: "sites",
          paint: {
            "circle-radius": ["case", ["==", ["get", "status"], "accepted"], 7, 5],
            "circle-color": [
              "match",
              ["get", "status"],
              "accepted", "#1a7f3a",
              "rejected", "#888",
              "installed", "#0b4d7a",
              "#cbcbcb",
            ],
            "circle-stroke-color": ["case", ["==", ["get", "is_manual"], true], "#c4a44a", "#222"],
            "circle-stroke-width": ["case", ["==", ["get", "is_manual"], true], 2.5, 1],
          },
        });
        map.on("click", "sites-circle", (e) => {
          // Single-marker click: select directly. For overlapping markers the
          // user picks via the hover popup buttons instead.
          const features = map.queryRenderedFeatures(e.point, { layers: ["sites-circle"] });
          if (features.length === 1) {
            const idx = (features[0].properties as { idx?: number })?.idx;
            if (typeof idx === "number") onSelectRef.current(idx);
          }
          // If >1, the hover popup is already showing the list; do nothing.
        });
        attachSiteHoverHandlers(map, hoverPopupRef, onSelectRef);
      } else {
        (map.getSource("sites") as maplibregl.GeoJSONSource).setData(sitesGeoJSON);
      }
      // Order: routes-line < routes-line-hover < sites-circle < routes-line-focused
      // The focused blue line is the most important visual cue, so it's
      // explicitly moved to the very top — including above the sign-site
      // markers. The markers are still clickable because MapLibre routes
      // pointer events to whichever layer's render covers the cursor,
      // and circle hits beat line hits when both match the same point.
      if (map.getLayer("sites-circle")) map.moveLayer("sites-circle");
      if (map.getLayer("routes-line-focused")) map.moveLayer("routes-line-focused");
    };
    if (map.loaded()) setup();
    else map.once("load", setup);
  }, [routesGeoJSON, sitesGeoJSON, onSelect]);

  // Map-level click for plain map (manual placement). Always wired — the
  // caller decides whether to act based on its mode.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!onMapClick) {
      map.getCanvas().style.cursor = "";
      return;
    }
    map.getCanvas().style.cursor = cursor || "crosshair";
    const handler = (e: maplibregl.MapMouseEvent) => {
      // Don't fire if the click landed on a sign-site marker — that has its own handler.
      const sites = map.queryRenderedFeatures(e.point, { layers: ["sites-circle"] });
      if (sites.length > 0) return;
      // Look at all routes under a small box around the click point — picks
      // up shared segments.
      const box: [maplibregl.PointLike, maplibregl.PointLike] = [
        [e.point.x - CLICK_TOLERANCE_PX, e.point.y - CLICK_TOLERANCE_PX],
        [e.point.x + CLICK_TOLERANCE_PX, e.point.y + CLICK_TOLERANCE_PX],
      ];
      const features = map.queryRenderedFeatures(box, { layers: ["routes-line"] });
      const seen = new Set<string>();
      const routes: string[] = [];
      for (const f of features) {
        const r = (f.properties as { rutenummer?: string })?.rutenummer;
        if (r && !seen.has(r)) { seen.add(r); routes.push(r); }
      }
      onMapClick(e.lngLat.lng, e.lngLat.lat, routes);
    };
    map.on("click", handler);
    return () => {
      map.off("click", handler);
      map.getCanvas().style.cursor = "";
    };
  }, [onMapClick, cursor]);

  // Apply focused-route styling: dim every non-focused route, bold the focused one.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      // Wait until BOTH layers are available — the routes source/layers are
      // added inside the (routesGeoJSON, sitesGeoJSON, onSelect)-deps effect,
      // which runs after the map's 'load' event. Without this guard the
      // focused filter could be set on a non-existent layer (silently fails).
      if (!map.getLayer("routes-line") || !map.getLayer("routes-line-focused")) {
        // Try again after the next render / source update.
        return;
      }
      if (focusedRoute) {
        map.setPaintProperty("routes-line", "line-opacity", [
          "case",
          ["==", ["get", "rutenummer"], focusedRoute],
          0.95,
          0.18,
        ]);
        map.setFilter("routes-line-focused", ["==", ["get", "rutenummer"], focusedRoute]);
        // Keep the focused layer above everything else, in case a later
        // moveLayer (e.g. in the source-update effect) put it below sites.
        map.moveLayer("routes-line-focused");
        console.debug("[signs_app] focus", focusedRoute, "filter applied");
      } else {
        map.setPaintProperty("routes-line", "line-opacity", 0.85);
        map.setFilter("routes-line-focused", ["==", ["get", "rutenummer"], "__none__"]);
      }
      map.triggerRepaint();
    };
    if (map.loaded()) apply();
    else map.once("load", apply);
  }, [focusedRoute]);

  // Switch base-map visibility when the user changes it
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      for (const id of ALL_BASE_LAYERS) {
        if (!map.getLayer(id)) continue;
        map.setLayoutProperty(id, "visibility", id === baseLayer ? "visible" : "none");
      }
    };
    if (map.loaded()) apply();
    else map.once("load", apply);
  }, [baseLayer]);

  // Photo markers — small HTML thumbnails pinned to each placed photo.
  // Stored in a ref so we can diff against the current `photos` and add/remove
  // without recreating every marker on every render.
  const photoMarkersRef = useRef<Map<number, maplibregl.Marker>>(new Map());
  const onPhotoClickRef = useRef(onPhotoClick);
  onPhotoClickRef.current = onPhotoClick;
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const visible = photosVisible !== false;
    const desired = new Map<number, FieldPhoto>();
    if (visible && photos) {
      for (const p of photos) {
        if (p.lon != null && p.lat != null) desired.set(p.id, p);
      }
    }
    // Remove markers for photos no longer present (or when hidden).
    for (const [id, marker] of photoMarkersRef.current) {
      if (!desired.has(id)) {
        marker.remove();
        photoMarkersRef.current.delete(id);
      }
    }
    // Add/update markers for current photos.
    for (const [id, p] of desired) {
      const existing = photoMarkersRef.current.get(id);
      if (existing) {
        existing.setLngLat([p.lon as number, p.lat as number]);
        continue;
      }
      const el = document.createElement("div");
      el.style.cssText = "width:32px;height:32px;border-radius:4px;overflow:hidden;"
        + "border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.4);cursor:pointer;"
        + "background:#ccc;";
      const img = document.createElement("img");
      img.src = p.thumb_url;
      img.alt = p.caption || "Bilde";
      img.style.cssText = "width:100%;height:100%;object-fit:cover;display:block;";
      img.draggable = false;
      el.appendChild(img);
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        onPhotoClickRef.current?.(id);
      });
      const marker = new maplibregl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([p.lon as number, p.lat as number])
        .addTo(map);
      photoMarkersRef.current.set(id, marker);
    }
  }, [photos, photosVisible]);

  // Clean up all photo markers on unmount.
  useEffect(() => {
    return () => {
      for (const m of photoMarkersRef.current.values()) m.remove();
      photoMarkersRef.current.clear();
    };
  }, []);

  // Recentre on selected site
  useEffect(() => {
    const map = mapRef.current;
    if (!map || selectedIdx == null) return;
    const s = sites[selectedIdx];
    if (s?.lon != null && s?.lat != null) {
      map.easeTo({ center: [s.lon, s.lat], zoom: Math.max(map.getZoom(), 12) });
    }
  }, [selectedIdx, sites]);

  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}

// ----- hover handlers (defined once at map setup) -----

interface SiteRow {
  idx: number;
  name: string;
  status: string;
  site_code: string;
  route_numbers: string;
  is_manual: boolean;
  is_endpoint: boolean;
  is_junction: boolean;
  n_panels: number;
}

function attachSiteHoverHandlers(
  map: maplibregl.Map,
  popupRef: React.MutableRefObject<maplibregl.Popup | null>,
  onSelectRef: React.MutableRefObject<(idx: number | null) => void>,
) {
  let lastKey = "";
  let closeTimer: number | null = null;
  const cancelClose = () => { if (closeTimer) { window.clearTimeout(closeTimer); closeTimer = null; } };
  const scheduleClose = (ms: number) => {
    cancelClose();
    closeTimer = window.setTimeout(() => {
      map.getCanvas().style.cursor = "";
      popupRef.current?.remove();
      lastKey = "";
    }, ms);
  };

  const onMove = (e: maplibregl.MapLayerMouseEvent) => {
    cancelClose();
    // Box-query so we catch overlapping markers, not just the topmost one.
    const features = map.queryRenderedFeatures(
      [
        [e.point.x - CLICK_TOLERANCE_PX, e.point.y - CLICK_TOLERANCE_PX],
        [e.point.x + CLICK_TOLERANCE_PX, e.point.y + CLICK_TOLERANCE_PX],
      ],
      { layers: ["sites-circle"] },
    );
    if (features.length === 0) return;
    const seen = new Set<number>();
    const rows: SiteRow[] = [];
    for (const f of features) {
      const p = f.properties as Partial<SiteRow>;
      if (typeof p?.idx !== "number" || seen.has(p.idx)) continue;
      seen.add(p.idx);
      rows.push({
        idx: p.idx,
        name: p.name || "",
        status: p.status || "",
        site_code: p.site_code || "",
        route_numbers: p.route_numbers || "",
        is_manual: !!p.is_manual,
        is_endpoint: !!p.is_endpoint,
        is_junction: !!p.is_junction,
        n_panels: p.n_panels ?? 0,
      });
    }
    if (rows.length === 0) return;
    map.getCanvas().style.cursor = "pointer";
    const key = rows.map((r) => r.idx).sort((a, b) => a - b).join("|");
    if (key === lastKey) return;
    lastKey = key;
    if (popupRef.current) {
      const dom = buildSitePopupDOM(rows, (idx) => {
        onSelectRef.current(idx);
        popupRef.current?.remove();
        lastKey = "";
        cancelClose();
      }, () => cancelClose(), () => scheduleClose(120));
      // Anchor popup at the first feature's coordinate so it doesn't jitter
      // when the cursor moves within the marker.
      const coords = (features[0].geometry as GeoJSON.Point).coordinates as [number, number];
      popupRef.current.setLngLat(coords).setDOMContent(dom).addTo(map);
    }
  };
  map.on("mousemove", "sites-circle", onMove);
  map.on("mouseleave", "sites-circle", () => scheduleClose(250));
}

function buildSitePopupDOM(
  rows: SiteRow[],
  onPick: (idx: number) => void,
  onEnter: () => void,
  onLeave: () => void,
): HTMLElement {
  const root = document.createElement("div");
  root.style.minWidth = "220px";
  root.addEventListener("mouseenter", onEnter);
  root.addEventListener("mouseleave", onLeave);
  if (rows.length > 1) {
    const hdr = document.createElement("div");
    hdr.textContent = `${rows.length} skilt overlapper`;
    hdr.style.cssText = "font-size:10px;color:#888;text-transform:uppercase;margin-bottom:4px";
    root.appendChild(hdr);
  }
  for (const r of rows) {
    const kind = r.is_manual
      ? "Manuelt"
      : r.is_endpoint && !r.is_junction
        ? "Endepunkt"
        : r.is_junction
          ? "Kryss"
          : "Skiltsted";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.style.cssText = [
      "display:block",
      "width:100%",
      "text-align:left",
      "padding:6px 8px",
      "margin-bottom:3px",
      "border:1px solid #e2e2e2",
      "background:white",
      "border-radius:3px",
      "cursor:pointer",
      "font-size:12px",
      "line-height:1.35",
    ].join(";");
    btn.innerHTML = `
      <div style="font-weight:600">${escapeHtml(r.name || "(uten navn)")}</div>
      <div style="color:#666">${r.site_code ? `<strong>${escapeHtml(r.site_code)}</strong> · ` : ""}${escapeHtml(kind)} · ${escapeHtml(r.status)}</div>
      ${r.route_numbers ? `<div style="color:#666;margin-top:2px">${escapeHtml(r.route_numbers)}</div>` : ""}
      <div style="color:#444;margin-top:2px">${r.n_panels} panel${r.n_panels === 1 ? "" : "er"}</div>
    `;
    btn.addEventListener("click", () => onPick(r.idx));
    root.appendChild(btn);
  }
  return root;
}

function attachRouteHoverHandlers(
  map: maplibregl.Map,
  popupRef: React.MutableRefObject<maplibregl.Popup | null>,
  focusedRouteRef: React.MutableRefObject<string | null>,
  onFocusRouteRef: React.MutableRefObject<(r: string | null) => void>,
  routeSummariesRef: React.MutableRefObject<Map<string, RouteSummary>>,
) {
  // We rebuild the popup DOM each move; track the last rendered route set so
  // we don't churn the DOM (and lose hover-on-popup) when the cursor moves
  // along the same segment.
  let lastKey = "";
  let closeTimer: number | null = null;
  const cancelClose = () => { if (closeTimer) { window.clearTimeout(closeTimer); closeTimer = null; } };
  const scheduleClose = (ms: number) => {
    cancelClose();
    closeTimer = window.setTimeout(() => {
      map.setFilter("routes-line-hover", ["==", ["get", "rutenummer"], "__none__"]);
      map.getCanvas().style.cursor = "";
      popupRef.current?.remove();
      lastKey = "";
    }, ms);
  };

  const onMove = (e: maplibregl.MapLayerMouseEvent) => {
    cancelClose();
    const features = map.queryRenderedFeatures(
      [
        [e.point.x - CLICK_TOLERANCE_PX, e.point.y - CLICK_TOLERANCE_PX],
        [e.point.x + CLICK_TOLERANCE_PX, e.point.y + CLICK_TOLERANCE_PX],
      ],
      { layers: ["routes-line"] },
    );
    if (features.length === 0) return;
    const seen = new Set<string>();
    const rows: { rutenummer: string; rutenavn: string }[] = [];
    for (const f of features) {
      const p = f.properties as { rutenummer?: string; rutenavn?: string };
      const r = p?.rutenummer;
      if (r && !seen.has(r)) { seen.add(r); rows.push({ rutenummer: r, rutenavn: p?.rutenavn || "" }); }
    }
    if (rows.length === 0) return;
    // Highlight all rutenumre under the cursor (gold).
    map.setFilter("routes-line-hover", ["in", ["get", "rutenummer"], ["literal", rows.map((r) => r.rutenummer)]]);
    map.getCanvas().style.cursor = "pointer";
    const key = rows.map((r) => r.rutenummer).join("|");
    if (key === lastKey) return;
    lastKey = key;
    if (popupRef.current) {
      const dom = buildRoutePopupDOM(
        rows,
        focusedRouteRef.current,
        routeSummariesRef.current,
        (r) => {
          // Toggle: clicking the already-focused route clears focus.
          const next = focusedRouteRef.current === r ? null : r;
          onFocusRouteRef.current(next);
          popupRef.current?.remove();
          lastKey = "";
          cancelClose();
        },
        () => cancelClose(),
        () => scheduleClose(120),
      );
      popupRef.current.setLngLat(e.lngLat).setDOMContent(dom).addTo(map);
    }
  };
  map.on("mousemove", "routes-line", onMove);
  map.on("mouseleave", "routes-line", () => scheduleClose(250));
}

function buildRoutePopupDOM(
  rows: { rutenummer: string; rutenavn: string }[],
  focused: string | null,
  summaries: Map<string, RouteSummary>,
  onPick: (rutenummer: string) => void,
  onEnter: () => void,
  onLeave: () => void,
): HTMLElement {
  const root = document.createElement("div");
  root.style.minWidth = "200px";
  root.addEventListener("mouseenter", onEnter);
  root.addEventListener("mouseleave", onLeave);
  const hdr = document.createElement("div");
  hdr.textContent = rows.length === 1 ? "Rute" : `${rows.length} ruter`;
  hdr.style.cssText = "font-size:10px;color:#888;text-transform:uppercase;margin-bottom:4px";
  root.appendChild(hdr);
  for (const r of rows) {
    const btn = document.createElement("button");
    btn.type = "button";
    const isFocused = focused === r.rutenummer;
    btn.style.cssText = [
      "display:block",
      "width:100%",
      "text-align:left",
      "padding:6px 8px",
      "margin-bottom:3px",
      `border:1px solid ${isFocused ? "#1a7fc4" : "#e2e2e2"}`,
      `background:${isFocused ? "#e8f1fb" : "white"}`,
      "border-radius:3px",
      "cursor:pointer",
      "font-size:12px",
      "line-height:1.35",
    ].join(";");
    const navn = formatRutenavn(r.rutenavn);
    const label = document.createElement("div");
    label.innerHTML = `<strong>${escapeHtml(r.rutenummer)}</strong>${navn ? ` — ${escapeHtml(navn)}` : ""}`;
    btn.appendChild(label);
    const sum = summaries.get(r.rutenummer);
    if (sum) {
      const route = document.createElement("div");
      const start = sum.start_name || "?";
      const end = sum.end_name || "?";
      const km = sum.length_km_displayed != null ? `${formatKmShort(sum.length_km_displayed)} km` : "";
      route.textContent = `${start} → ${end}${km ? ` · ${km}` : ""}`;
      route.style.cssText = "color:#666;font-size:11px;margin-top:2px";
      btn.appendChild(route);
    }
    if (isFocused) {
      const tag = document.createElement("div");
      tag.textContent = "fokusert — klikk for å fjerne";
      tag.style.cssText = "color:#1a7fc4;font-size:10px;margin-top:2px";
      btn.appendChild(tag);
    }
    btn.addEventListener("click", () => onPick(r.rutenummer));
    root.appendChild(btn);
  }
  return root;
}

function formatKmShort(km: number): string {
  return km < 10 ? km.toFixed(1) : String(Math.round(km));
}

function formatRutenavn(s: string | undefined | null): string {
  // Many turrutebasen rows carry rutenavn='Ukjent' as a placeholder — treat it
  // as "no name" for the UI so we don't repeat noise on every line.
  if (!s) return "";
  const trimmed = s.trim();
  if (!trimmed) return "";
  if (trimmed.toLowerCase() === "ukjent") return "";
  return trimmed;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
