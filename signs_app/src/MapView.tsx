import { useEffect, useMemo, useRef } from "react";
import maplibregl from "maplibre-gl";
import { api } from "./api";
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
  /** Area code — needed so the photo layer can call the bulk-thumbnails
   *  endpoint scoped to one area. */
  areaCode: string;
  /** Placed (geotagged) field photos to render as clustered thumbnail markers. */
  photos?: FieldPhoto[];
  /** Called when one or more photos are opened from the map — a single dot
   *  passes one id, a cluster passes the ids of every photo inside it. */
  onPhotosOpen?: (photoIds: number[]) => void;
  /** Hide the photo layer when false (toggled by the layer panel in the
   *  map's top-left). */
  photosVisible?: boolean;
  onPhotosVisibleChange?: (v: boolean) => void;
}

const BREHEIMEN_CENTER: [number, number] = [7.5, 61.7];

// Kartverket's open WMTS cache. {z}/{y}/{x} maps directly to
// {TileMatrix}/{TileRow}/{TileCol}. No auth, attribution required.
const KARTVERKET_TILES = (layer: "topo" | "topograatone") =>
  `https://cache.kartverket.no/v1/wmts/1.0.0/${layer}/default/webmercator/{z}/{y}/{x}.png`;

const BASE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  // Glyphs endpoint is required for any symbol layer that renders `text-field`
  // (e.g. the photo-cluster count badge). Free MapLibre demo fonts work fine
  // for short numeric labels.
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
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

// Photo-marker sizing. The thumbs the API returns are 200×200, so icon-size
// 0.13 → ~26 px on screen — small enough to leave room around the sign-site
// dots underneath, large enough that you can still read the thumbnail.
const PHOTO_ICON_SIZE = 0.13;
// Where to draw the cluster count badge, in screen pixels. Aligned to the
// upper-right corner of the icon (which is bottom-anchored, so it extends
// upward from the feature point).
const PHOTO_BADGE_OFFSET: [number, number] = [11, -22];

// A 200×200 placeholder used in the `coalesce` of the photo layers' icon-image.
// Renders whenever the real thumb hasn't been registered yet so the user always
// sees something at a cluster's location instead of just the count badge
// hovering in the air. Same dimensions as the real thumbs so icon-size 0.13
// scales it consistently.
function makeClusterFallbackIcon(): ImageData {
  const size = 200;
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const ctx = c.getContext("2d");
  if (!ctx) return new ImageData(size, size);
  ctx.fillStyle = "#1a7fc4";
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2 - 8, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 8;
  ctx.stroke();
  ctx.font = "bold 110px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#ffffff";
  ctx.fillText("📷", size / 2, size / 2 + 5);
  return ctx.getImageData(0, 0, size, size);
}

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
  areaCode,
  photos,
  onPhotosOpen,
  photosVisible,
  onPhotosVisibleChange,
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
      // Don't fire if the click landed on a sign-site marker or a photo
      // dot/cluster — those layers have their own handlers, and re-firing
      // placement here would (e.g. in place-photo mode) drop a pin on top
      // of the photo the user actually meant to open.
      const layers = ["sites-circle", "photos-single", "photos-cluster-icon"]
        .filter((id) => map.getLayer(id));
      const hit = map.queryRenderedFeatures(e.point, { layers });
      if (hit.length > 0) return;
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

  // Photo layer — a clustered GeoJSON source feeds three layers:
  //   photos-cluster        : circle bubble shown for clusters of N>=2 photos
  //   photos-cluster-count  : the N label on the bubble
  //   photos-single         : thumbnail icon for unclustered photos
  //
  // Each thumbnail is registered as a map image (`photo-<id>`) on demand and
  // referenced by `icon-image` so the renderer picks the right thumb per
  // feature. Loaded image ids are tracked in a ref to avoid reloading.
  const onPhotosOpenRef = useRef(onPhotosOpen);
  onPhotosOpenRef.current = onPhotosOpen;
  const loadedPhotoImagesRef = useRef<Set<number>>(new Set());
  // Photos whose thumb fetch already failed once. Cached so a panning user
  // doesn't keep re-requesting the same broken URL on every moveend.
  const failedPhotoImagesRef = useRef<Set<number>>(new Set());
  // In-flight per-photo lazy loads — keyed by id so styleimagemissing doesn't
  // fire ten parallel fetches for the same image during initial paint.
  const inflightLazyLoadsRef = useRef<Set<number>>(new Set());

  // The cluster-icon's image-id is computed from feature properties at render
  // time. If the bulk pre-load hasn't reached that id yet (or failed), MapLibre
  // fires `styleimagemissing` for that name — we fetch the single thumb on
  // demand and register it. This is the *real* reason photos finally show up:
  // no matter what races / failures happen during pre-load, MapLibre will ask
  // for every image it actually needs and we serve it.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const handler = async (e: { id: string }) => {
      const id = e.id;
      if (!id.startsWith("photo-")) return;
      const photoId = Number.parseInt(id.slice("photo-".length), 10);
      if (!Number.isFinite(photoId)) return;
      if (map.hasImage(id)) return;
      if (inflightLazyLoadsRef.current.has(photoId)) return;
      inflightLazyLoadsRef.current.add(photoId);
      try {
        const resp = await map.loadImage(`/api/v1/photos/${photoId}/file?size=thumb`);
        if (resp && resp.data && !map.hasImage(id)) {
          map.addImage(id, resp.data);
          loadedPhotoImagesRef.current.add(photoId);
        }
      } catch (err) {
        failedPhotoImagesRef.current.add(photoId);
        console.warn(`[signs_app] lazy thumb load failed for ${id}:`, err);
      } finally {
        inflightLazyLoadsRef.current.delete(photoId);
      }
    };
    map.on("styleimagemissing", handler);
    return () => { map.off("styleimagemissing", handler); };
  }, []);

  const photosGeoJSON = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: (photos ?? [])
      .filter((p) => p.lon != null && p.lat != null)
      .map((p) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.lon as number, p.lat as number] },
        properties: { id: p.id, icon: `photo-${p.id}` },
      })),
  }), [photos]);

  // Bootstrap the photo source/layers + click handlers once, then keep data
  // in sync via setData on subsequent runs.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const setup = () => {
      if (!map.getSource("photos-src")) {
        map.addSource("photos-src", {
          type: "geojson",
          data: photosGeoJSON,
          cluster: true,
          clusterRadius: 40,
          clusterMaxZoom: 16,
          // Carry the smallest photo id in each cluster through as a property,
          // so the cluster icon can show that photo's thumbnail. Any single
          // representative is fine — the user sees the full set in the
          // lightbox after clicking.
          clusterProperties: { first_id: ["min", ["get", "id"]] },
        });
        // Register a fallback icon so a cluster always renders SOMETHING even
        // before the representative photo's thumbnail has loaded. Without this,
        // the brief window between "cluster appears on map" and "thumb arrives"
        // shows only the count badge — looking like the icon is broken.
        if (!map.hasImage("photo-cluster-fallback")) {
          map.addImage("photo-cluster-fallback", makeClusterFallbackIcon());
        }
        // Cluster icon: thumbnail of the representative photo, falling back to
        // a generic camera bubble if that thumb isn't registered (e.g. it's
        // still loading, or its bbox-filtered fetch hasn't reached this id).
        map.addLayer({
          id: "photos-cluster-icon",
          type: "symbol",
          source: "photos-src",
          filter: ["has", "point_count"],
          layout: {
            "icon-image": [
              "coalesce",
              ["image", ["concat", "photo-", ["to-string", ["get", "first_id"]]]],
              ["image", "photo-cluster-fallback"],
            ],
            "icon-size": PHOTO_ICON_SIZE,
            "icon-allow-overlap": true,
            "icon-anchor": "bottom",
          },
        });
        // Small red badge in the upper-right corner of the cluster icon.
        // circle-translate is in screen pixels (viewport anchor), so the
        // offset stays put as the user zooms.
        map.addLayer({
          id: "photos-cluster-badge",
          type: "circle",
          source: "photos-src",
          filter: ["has", "point_count"],
          paint: {
            "circle-radius": 9,
            "circle-color": "#c43d3d",
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 1.5,
            "circle-translate": PHOTO_BADGE_OFFSET,
            "circle-translate-anchor": "viewport",
          },
        });
        map.addLayer({
          id: "photos-cluster-badge-text",
          type: "symbol",
          source: "photos-src",
          filter: ["has", "point_count"],
          layout: {
            "text-field": ["get", "point_count_abbreviated"],
            "text-font": ["Noto Sans Bold"],
            "text-size": 11,
            "text-allow-overlap": true,
            "text-ignore-placement": true,
          },
          paint: {
            "text-color": "#ffffff",
            "text-translate": PHOTO_BADGE_OFFSET,
            "text-translate-anchor": "viewport",
          },
        });
        map.addLayer({
          id: "photos-single",
          type: "symbol",
          source: "photos-src",
          filter: ["!", ["has", "point_count"]],
          layout: {
            "icon-image": [
              "coalesce",
              ["image", ["get", "icon"]],
              ["image", "photo-cluster-fallback"],
            ],
            "icon-size": PHOTO_ICON_SIZE,
            "icon-allow-overlap": true,
            "icon-anchor": "bottom",
          },
        });

        map.on("click", "photos-single", (e) => {
          const f = e.features?.[0];
          const id = f && (f.properties as { id?: number })?.id;
          if (typeof id === "number") {
            e.originalEvent?.stopPropagation?.();
            onPhotosOpenRef.current?.([id]);
          }
        });
        map.on("click", "photos-cluster-icon", (e) => {
          const f = e.features?.[0];
          const clusterId = f && (f.properties as { cluster_id?: number })?.cluster_id;
          if (clusterId == null) return;
          const source = map.getSource("photos-src") as maplibregl.GeoJSONSource;
          // Pull every leaf at once — cluster paging in the lightbox is the
          // whole point. Infinity is the documented "all of them" sentinel.
          source.getClusterLeaves(clusterId, Infinity, 0).then((leaves) => {
            const ids: number[] = [];
            for (const lf of leaves) {
              const lid = (lf.properties as { id?: number })?.id;
              if (typeof lid === "number") ids.push(lid);
            }
            if (ids.length > 0) {
              e.originalEvent?.stopPropagation?.();
              onPhotosOpenRef.current?.(ids);
            }
          }).catch(() => { /* cluster ids can briefly go stale during data swaps */ });
        });

        for (const lid of ["photos-cluster-icon", "photos-single"]) {
          map.on("mouseenter", lid, () => { map.getCanvas().style.cursor = "pointer"; });
          map.on("mouseleave", lid, () => { map.getCanvas().style.cursor = ""; });
        }
      } else {
        (map.getSource("photos-src") as maplibregl.GeoJSONSource).setData(photosGeoJSON);
      }
      // Restack so sign-sites and the focused route line render above photos
      // (the user's request: photo markers shouldn't visually swamp the green
      // site dots). Order from bottom up: routes → photos → sites → focus.
      if (map.getLayer("sites-circle")) map.moveLayer("sites-circle");
      if (map.getLayer("routes-line-focused")) map.moveLayer("routes-line-focused");
    };
    if (map.loaded()) setup();
    else map.once("load", setup);
  }, [photosGeoJSON]);

  // Load thumbnail images in BULK. One GET to /photos/thumbnails returns
  // every thumb that has at least one photo in the (padded) viewport as
  // base64 JPEGs — we decode each via an HTMLImageElement and register it
  // as a map image keyed by `photo-<id>`. This replaces N individual fetches
  // with a single round trip, which is the difference between "thumbnails
  // pop in instantly" and "user gives up before they appear".
  //
  // Triggers:
  //   - photos prop changes (a new photo was added / one was placed)
  //   - moveend (panning brought new viewport photos into range)
  //   - the map's first "load" event (style may not have been ready when the
  //     first call came in)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !photos) return;
    let cancelled = false;
    const loaded = loadedPhotoImagesRef.current;
    const failed = failedPhotoImagesRef.current;

    // map.addImage rejects calls made before the style is fully parsed —
    // and MapLibre's "load" event is one-shot, so if the photos arrive
    // before that event fires, attaching `.once("load")` after the fact
    // will never trigger. Poll isStyleLoaded() until it's true (or give up
    // after ~3 s). This single helper is the difference between thumbs
    // rendering and the user staring at empty cluster badges.
    const safeAddImage = (key: string, img: HTMLImageElement | ImageBitmap): Promise<boolean> => {
      return new Promise((resolve) => {
        let attempts = 0;
        const tryAdd = () => {
          if (cancelled) { resolve(false); return; }
          if (map.hasImage(key)) { resolve(true); return; }
          if (!map.isStyleLoaded()) {
            if (++attempts < 30) { setTimeout(tryAdd, 100); return; }
            console.warn(`[signs_app] style never loaded for ${key}`);
            resolve(false);
            return;
          }
          try {
            map.addImage(key, img);
            resolve(true);
          } catch (e) {
            console.warn(`[signs_app] addImage failed for ${key}:`, e);
            resolve(false);
          }
        };
        tryAdd();
      });
    };

    const decodeAndAdd = async (id: number, b64: string) => {
      const key = `photo-${id}`;
      if (map.hasImage(key)) { loaded.add(id); return; }
      // map.loadImage handles data: URLs and produces an ImageBitmap /
      // HTMLImageElement that addImage definitely accepts. Doing the decode
      // through MapLibre instead of `new Image()` + addImage(HTMLImageElement)
      // is the documented-happy-path and avoids dimension/timing surprises.
      let resp;
      try {
        resp = await map.loadImage(`data:image/jpeg;base64,${b64}`);
      } catch (e) {
        failed.add(id);
        console.warn(`[signs_app] decode failed for thumb id=${id}:`, e);
        return;
      }
      if (cancelled || !resp || !resp.data) return;
      const ok = await safeAddImage(key, resp.data);
      if (ok) loaded.add(id);
    };

    const loadVisible = async () => {
      if (cancelled) return;
      // Compute the photos we still need: in the (padded) viewport, not
      // already loaded, not in the permanent-fail set. If none, skip the
      // network call entirely.
      const b = map.getBounds();
      const sw = b.getSouthWest(), ne = b.getNorthEast();
      const dx = (ne.lng - sw.lng) * 0.5;
      const dy = (ne.lat - sw.lat) * 0.5;
      const minLng = sw.lng - dx, maxLng = ne.lng + dx;
      const minLat = sw.lat - dy, maxLat = ne.lat + dy;
      const needed: number[] = [];
      for (const p of photos) {
        if (p.lon == null || p.lat == null) continue;
        if (p.lon < minLng || p.lon > maxLng) continue;
        if (p.lat < minLat || p.lat > maxLat) continue;
        if (loaded.has(p.id) || failed.has(p.id)) continue;
        needed.push(p.id);
      }
      if (needed.length === 0) return;
      try {
        const resp = await api.getPhotoThumbnails(areaCode, {
          minLng, minLat, maxLng, maxLat,
        });
        if (cancelled) return;
        // Decode in parallel — image.decode() is async but cheap.
        await Promise.all(resp.thumbs.map((t) => decodeAndAdd(t.id, t.data)));
      } catch (e) {
        console.warn("[signs_app] bulk thumb fetch failed:", e);
      }
    };

    loadVisible();
    const onMoveEnd = () => { loadVisible(); };
    map.on("moveend", onMoveEnd);
    const onLoad = () => { loadVisible(); };
    map.on("load", onLoad);
    return () => {
      cancelled = true;
      map.off("moveend", onMoveEnd);
      map.off("load", onLoad);
    };
  }, [photos, areaCode]);

  // Toggle photo-layer visibility (topbar button). Check layer existence
  // rather than `map.loaded()` — the latter flips back to false during tile
  // loads, but the "load" event only ever fires once, so any once-load
  // callback queued after the first load would never run.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      const v = photosVisible !== false ? "visible" : "none";
      for (const lid of ["photos-cluster-icon", "photos-cluster-badge", "photos-cluster-badge-text", "photos-single"]) {
        if (map.getLayer(lid)) map.setLayoutProperty(lid, "visibility", v);
      }
    };
    if (map.getLayer("photos-single") || map.getLayer("photos-cluster-icon")) apply();
    else map.once("load", apply);
  }, [photosVisible]);

  // Recentre on selected site
  useEffect(() => {
    const map = mapRef.current;
    if (!map || selectedIdx == null) return;
    const s = sites[selectedIdx];
    if (s?.lon != null && s?.lat != null) {
      map.easeTo({ center: [s.lon, s.lat], zoom: Math.max(map.getZoom(), 12) });
    }
  }, [selectedIdx, sites]);

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />
      <div
        style={{
          position: "absolute", top: 10, left: 10, zIndex: 1,
          background: "rgba(255,255,255,0.92)", borderRadius: 4,
          padding: "6px 10px", fontSize: 12,
          boxShadow: "0 1px 3px rgba(0,0,0,0.25)",
          userSelect: "none",
        }}
      >
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={photosVisible !== false}
            onChange={(e) => onPhotosVisibleChange?.(e.target.checked)}
          />
          <span>📷 Bilder</span>
          <span style={{ color: "#666" }}>({(photos ?? []).filter((p) => p.lon != null && p.lat != null).length})</span>
        </label>
      </div>
    </div>
  );
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
