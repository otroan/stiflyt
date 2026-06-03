import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { IconAlertTriangle, IconCamera, IconDownload, IconHomeDollar, IconInfoCircle, IconMapPin, IconRoute, IconRoute2 } from "@tabler/icons-react";
import { api } from "./api";
import type { CandidatesResponse, FieldPhoto, GeometryOwnerItem, GpxTrack, PlaceSearchResult, PointMatrikkelResponse, RouteAnnotation, RouteListItem, RouteSummary, SessionUser, SignSite } from "./types";
import MapView, { type BaseLayerId } from "./MapView";
import SiteEditor from "./SiteEditor";
import AreaReport from "./AreaReport";
import GrunneierPanel from "./GrunneierPanel";
import SearchBox from "./SearchBox";
import PhotoPanel, { PhotoLightbox } from "./PhotoPanel";
import FloatingToolbar from "./FloatingToolbar";
import ExportTab from "./ExportTab";
import RoutePanel from "./RoutePanel";
import AreaValidationPanel from "./AreaValidationPanel";
import GpxPanel from "./GpxPanel";
import { notifyError } from "./notify";
import { notifications } from "@mantine/notifications";

type SidebarTab = "sites" | "rute" | "kvalitet" | "photos" | "spor" | "export" | "grunneier" | "about";

const LOGIN_ERROR_MESSAGES: Record<string, string> = {
  not_allowed: "E-postadressen din står ikke i tilgangslisten. Kontakt en administrator.",
  email_unverified: "Google-kontoen din har ikke verifisert e-postadressen.",
  oauth_error: "Innloggingen ble avbrutt eller feilet. Prøv igjen.",
};

function LoginScreen({ errorCode }: { errorCode: string | null }) {
  const msg = errorCode ? LOGIN_ERROR_MESSAGES[errorCode] ?? `Feil: ${errorCode}` : null;
  return (
    <Center mih="100vh" bg="gray.0">
      <Paper p="xl" shadow="md" radius="md" w={380}>
        <Stack gap="md" align="center">
          <Title order={2} c="brand.7">Skiltverktøy</Title>
          <Text c="dimmed" size="sm" ta="center">
            Logg inn med Google-kontoen din for å fortsette.
          </Text>
          {msg && (
            <Alert color="red" w="100%" variant="light">
              {msg}
            </Alert>
          )}
          <Button
            component="a"
            href={`/api/v1/auth/login?next=${encodeURIComponent(import.meta.env.BASE_URL)}`}
            color="brand"
            size="md"
            fullWidth
          >
            Logg inn med Google
          </Button>
        </Stack>
      </Paper>
    </Center>
  );
}

const BASE_LAYER_STORAGE_KEY = "signs_app:baseLayer";
const BASE_LAYER_LABELS: Record<BaseLayerId, string> = {
  osm: "OpenStreetMap",
  topo4: "Topo4 (Kartverket)",
  topo4graatone: "Topo4 gråtone",
};


const DEFAULT_AREA = "bre";

type Mode = "browse" | "add-manual" | "place-photo" | "place-work-marker";

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
      .then((u) => {
        if (cancelled) return;
        setMe(u);
        // Propagate the authenticated identity into api.ts so writes carry
        // X-User: <email> (persisted as recorded_by/updated_by/uploaded_by).
        api.setCurrentUser(u?.email ?? null);
      })
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

  // When the user picks a site on the map, surface its editor. Without this,
  // clicking a marker while the Export tab is open does nothing visible.
  const [selectedSiteKey, setSelectedSiteKeyInner] = useState<string | null>(null);
  const setSelectedSiteKey = (k: string | null) => {
    setSelectedSiteKeyInner(k);
    if (k) setSidebarTab("sites");
  };

  const [areaCode, setAreaCode] = useState<string>(DEFAULT_AREA);
  const [candidates, setCandidates] = useState<CandidatesResponse | null>(null);
  const [routes, setRoutes] = useState<RouteListItem[]>([]);
  const [routeSummaries, setRouteSummaries] = useState<Map<string, RouteSummary>>(new Map());
  // Tracked by stable key (sign_site_id or anchor_node_id) so it survives
  // reorderings of the candidates list (manual sites are appended after
  // anchor sites and may shuffle when rows are added/removed).
  // selectedSiteIdx (array position) is recomputed from the key below.
  // The state itself is defined earlier alongside the sidebarTab auto-switch.
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<Mode>("browse");
  const [baseLayer, setBaseLayer] = useState<BaseLayerId>(() => {
    const stored = localStorage.getItem(BASE_LAYER_STORAGE_KEY);
    return stored === "topo4" || stored === "topo4graatone" ? stored : "osm";
  });
  useEffect(() => { localStorage.setItem(BASE_LAYER_STORAGE_KEY, baseLayer); }, [baseLayer]);
  const [focusedRoute, setFocusedRoute] = useState<string | null>(null);
  // Loop arms highlighted on the map by the Validering sub-tab (one coloured
  // line per arm). Empty when no loop route is being inspected.
  const [loopArms, setLoopArms] = useState<{ color: string; geometry: GeoJSON.Geometry }[]>([]);
  // Bumped to force an area reload (route geometries + candidates) after a
  // correction changes a route's shape — e.g. excluding a loop arm.
  const [areaReloadKey, setAreaReloadKey] = useState(0);
  // When navigating from the Kvalitet list, open the route panel directly on
  // its Validering sub-tab. Cleared after it's consumed.
  const [routeInitialSubTab, setRouteInitialSubTab] = useState<"validation" | null>(null);
  // Bumped to force RoutePanel to re-fetch its annotations list after an
  // external write (e.g. dropping a work marker via the map). Without this,
  // the new marker shows on the map layer but not in the Rute→Arbeid list
  // until the user re-focuses the route.
  const [annotationsBumpKey, setAnnotationsBumpKey] = useState(0);
  // Escape clears route focus — backup for users who can't quickly relocate
  // the hovered popup. Only binds when a route is actually focused so we
  // don't fight with text-input Escape elsewhere.
  useEffect(() => {
    if (!focusedRoute) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const tgt = e.target as HTMLElement | null;
      const typing = tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.isContentEditable);
      if (typing) return;
      setFocusedRoute(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusedRoute]);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>("sites");

  // Auto-open the Rute tab when the user focuses a route on the map. Don't
  // hijack the tab if they're in the middle of editing a site or placing a
  // photo — those modes take precedence.
  useEffect(() => {
    if (!focusedRoute) return;
    if (mode !== "browse") return;
    setSidebarTab("rute");
    // mode lives below; we deliberately read it from the closure here. The
    // effect re-runs only when focusedRoute changes, which is the trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusedRoute]);

  // Cultural-heritage (kulturminner) overlay for the focused route: enkeltminne
  // points/areas + sikringssone polygons within 50 m, as one FeatureCollection.
  const [kulturminnerFC, setKulturminnerFC] = useState<GeoJSON.FeatureCollection | null>(null);
  // kulturminneid currently hovered in the RoutePanel list — highlights its
  // polygon/point on the map.
  const [hoveredKulturminneId, setHoveredKulturminneId] = useState<string | null>(null);
  useEffect(() => {
    if (!focusedRoute) { setKulturminnerFC(null); return; }
    let cancelled = false;
    api.getRouteKulturminner(focusedRoute)
      .then((r) => {
        if (cancelled) return;
        if (!r.available) { setKulturminnerFC(null); return; }
        const features: GeoJSON.Feature[] = [];
        for (const k of r.kulturminner) {
          if (k.geometry) features.push({
            type: "Feature", geometry: k.geometry,
            properties: {
              kind: "enkeltminne", kulturminneid: k.kulturminneid, navn: k.navn,
              kategori: k.kategori, art: k.art, datering: k.datering,
              vernetype: k.vernetype, link: k.link, distance_m: k.distance_m,
            },
          });
        }
        for (const s of r.sikringssoner) {
          if (s.geometry) features.push({
            type: "Feature", geometry: s.geometry,
            properties: {
              kind: "sikringssone", kulturminneid: s.kulturminneid, navn: "Sikringssone",
              link: s.link, distance_m: s.distance_m,
            },
          });
        }
        setKulturminnerFC({ type: "FeatureCollection", features });
      })
      .catch(() => { if (!cancelled) setKulturminnerFC(null); });
    return () => { cancelled = true; };
  }, [focusedRoute]);

  // --- Field photos state ---
  const [photos, setPhotos] = useState<FieldPhoto[]>([]);
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
      notifyError(e);
    }
  };
  useEffect(() => { if (me) refreshPhotos(); }, [areaCode, me]);

  // --- GPX tracks (actually-walked overlay) ---
  const [gpxTracks, setGpxTracks] = useState<GpxTrack[]>([]);
  const [gpxVisible, setGpxVisible] = useState(true);
  const [gpxLoading, setGpxLoading] = useState(false);
  const refreshGpx = async () => {
    setGpxLoading(true);
    try {
      const r = await api.listGpxTracks(areaCode);
      setGpxTracks(r.tracks);
    } catch (e) {
      notifyError(e);
    } finally {
      setGpxLoading(false);
    }
  };
  useEffect(() => { if (me) refreshGpx(); }, [areaCode, me]);
  const handleUploadGpx = async (files: File[]) => {
    const total = files.length;
    const notifId = `gpx-upload-${Date.now()}`;
    const failed: { name: string; error: string }[] = [];
    let done = 0;

    const baseTitle = total > 1 ? `Laster opp GPX (${total})` : "Laster opp GPX";
    notifications.show({
      id: notifId,
      loading: true,
      autoClose: false,
      withCloseButton: false,
      title: baseTitle,
      message: `0 / ${total}`,
    });

    for (const f of files) {
      try {
        await api.uploadGpx(areaCode, f);
      } catch (e) {
        failed.push({ name: f.name, error: e instanceof Error ? e.message : String(e) });
      }
      done += 1;
      notifications.update({
        id: notifId,
        loading: true,
        autoClose: false,
        withCloseButton: false,
        title: baseTitle,
        message: `${done} / ${total}${failed.length ? ` · ${failed.length} feilet` : ""}`,
      });
    }

    const ok = total - failed.length;
    if (failed.length === 0) {
      notifications.update({
        id: notifId,
        loading: false,
        autoClose: 4000,
        withCloseButton: true,
        color: "green",
        title: "GPX-opplasting fullført",
        message: `${ok} fil${ok === 1 ? "" : "er"} lastet opp.`,
      });
    } else {
      const preview = failed.slice(0, 8).map((x) => `• ${x.name}: ${x.error}`).join("\n");
      const more = failed.length > 8 ? `\n…og ${failed.length - 8} til` : "";
      notifications.update({
        id: notifId,
        loading: false,
        autoClose: false,
        withCloseButton: true,
        color: ok > 0 ? "orange" : "red",
        title: ok > 0 ? "GPX-opplasting fullført med feil" : "GPX-opplasting feilet",
        message: `${ok} OK · ${failed.length} feilet:\n${preview}${more}`,
        style: { whiteSpace: "pre-wrap" },
      });
      console.warn("GPX upload failures:", failed);
    }

    await refreshGpx();
  };
  const handleDeleteGpx = async (id: number) => {
    try {
      await api.deleteGpx(id);
      setGpxTracks((prev) => prev.filter((t) => t.id !== id));
    } catch (e) {
      notifyError(e);
    }
  };

  // --- Work markers (route_annotations of kind work_*) ---
  const [workMarkers, setWorkMarkers] = useState<RouteAnnotation[]>([]);
  const [workMarkersVisible, setWorkMarkersVisible] = useState(true);
  const [hoveredAnnotationId, setHoveredAnnotationId] = useState<number | null>(null);

  // --- Grunneier (matrikkelenhet by point) ---
  // Map click while sidebarTab === "grunneier" runs api.pointMatrikkelenhet(lat,lon);
  // the response polygon is drawn on the map and the details/owners render in
  // the Grunneier sidebar panel. Loading flag drives a Loader on the panel.
  const [matrikkelResult, setMatrikkelResult] = useState<PointMatrikkelResponse | null>(null);
  const [matrikkelLoading, setMatrikkelLoading] = useState(false);
  const [matrikkelError, setMatrikkelError] = useState<string | null>(null);
  // --- Grunneier (owners-by-route, Phase 3) ---
  // The Grunneier panel toggles between "punkt" (Phase 2 point lookup) and
  // "ruter" mode. In Ruter mode the user clicks the already-rendered DNT route
  // lines to pick routes (no separate overlay); "Hent eiere" runs POST
  // /geometry/owners over each selected route's geometry and aggregates the
  // matrikkelenhet vectors into a deduplicated owner list.
  const [grunneierMode, setGrunneierMode] = useState<"punkt" | "ruter">("punkt");
  const [selectedRutenumre, setSelectedRutenumre] = useState<Set<string>>(new Set());
  const selectedRoutes = useMemo(() => [...selectedRutenumre], [selectedRutenumre]);
  const [routeOwners, setRouteOwners] = useState<{ items: GeometryOwnerItem[]; totalKm: number; routeCount: number; errorCount: number } | null>(null);
  const [routeOwnersLoading, setRouteOwnersLoading] = useState(false);
  const [routeOwnersError, setRouteOwnersError] = useState<string | null>(null);
  // Geometry of the owner row currently hovered in the batch result — drawn as
  // a bright spotlight on the map.
  const [highlightGeometry, setHighlightGeometry] = useState<GeoJSON.Geometry | null>(null);

  // --- Map place search ---
  const [flyTo, setFlyTo] = useState<{ lon: number; lat: number; nonce: number } | null>(null);
  const flyNonceRef = useRef(0);
  const handleSearchSelect = (r: PlaceSearchResult) => {
    flyNonceRef.current += 1;
    setFlyTo({ lon: r.lon, lat: r.lat, nonce: flyNonceRef.current });
    // For a route hit, also focus it so the matching line stands out.
    if (r.type === "rute" && r.rutenummer) setFocusedRoute(r.rutenummer);
  };

  // Reset the route selection + owner result when switching area so stale
  // rutenumre from another area don't linger in the panel.
  useEffect(() => {
    setSelectedRutenumre(new Set());
    setRouteOwners(null);
    setRouteOwnersError(null);
    setHighlightGeometry(null);
  }, [areaCode]);

  const toggleRouteSelection = (rutenummer: string) => {
    setSelectedRutenumre((prev) => {
      const next = new Set(prev);
      if (next.has(rutenummer)) next.delete(rutenummer);
      else next.add(rutenummer);
      return next;
    });
  };

  const clearRouteSelection = () => {
    setSelectedRutenumre(new Set());
    setRouteOwners(null);
    setRouteOwnersError(null);
  };

  const [routeOwnersExporting, setRouteOwnersExporting] = useState(false);
  const exportRouteOwners = async () => {
    if (!routeOwners || routeOwners.items.length === 0) return;
    setRouteOwnersExporting(true);
    try {
      await api.downloadOwnersExcel(
        routeOwners.items,
        { rutenummer: [...selectedRutenumre].join(", "), total_length_km: routeOwners.totalKm },
        [...selectedRutenumre].join(", "),
      );
    } catch (e) {
      notifyError(e, "Klarte ikke å lage Excel-rapport");
    } finally {
      setRouteOwnersExporting(false);
    }
  };

  const fetchRouteOwners = async () => {
    const rns = [...selectedRutenumre];
    if (rns.length === 0) return;
    setRouteOwnersLoading(true);
    setRouteOwnersError(null);
    // Resolve each rutenummer to its rendered geometry (marked first, else the
    // unmarked fallback) and send it as-is. Routes are MultiLineString; the
    // backend handles that natively, so we must NOT flatten to a LineString —
    // stitching disjoint parts would draw spurious straight jumps and corrupt
    // both the owner match and the per-parcel highlight segment.
    const geoms: GeoJSON.Geometry[] = [];
    for (const rn of rns) {
      const r = routes.find((x) => x.rutenummer === rn);
      const g = (r?.route_geometry ?? r?.route_geometry_unmarked) as GeoJSON.Geometry | null | undefined;
      if (g && (g.type === "LineString" || g.type === "MultiLineString")) geoms.push(g);
    }
    const results = await Promise.allSettled(geoms.map((g) => api.geometryOwners(g)));
    const all: GeometryOwnerItem[] = [];
    let totalM = 0;
    let errorCount = 0;
    for (const r of results) {
      if (r.status === "fulfilled") {
        all.push(...(r.value.matrikkelenhet_vector || []));
        totalM += r.value.total_length_meters || 0;
      } else {
        errorCount += 1;
      }
    }
    // Deduplicate by matrikkelenhet — adjacent routes hit the same parcel.
    const seen = new Map<string, GeometryOwnerItem>();
    for (const it of all) {
      const key = it.matrikkelenhet || `${it.kommunenummer}-${it.gardsnummer}/${it.bruksnummer}`;
      if (!seen.has(key)) seen.set(key, it);
    }
    const items = [...seen.values()].sort((a, b) =>
      (a.matrikkelenhet || "").localeCompare(b.matrikkelenhet || "", "nb", { numeric: true }),
    );
    setRouteOwners({ items, totalKm: totalM / 1000, routeCount: rns.length, errorCount });
    setRouteOwnersLoading(false);
    if (items.length === 0 && errorCount > 0) {
      setRouteOwnersError("Klarte ikke å hente eiere for de valgte rutene.");
    }
  };
  // Selected work-kind for the next placement click. Set by the kind picker
  // in RoutePanel's Arbeid sub-tab; the toolbar's IconTool button defaults to
  // work_other.
  const [pendingWorkKind, setPendingWorkKind] = useState<RouteAnnotation["kind"]>("work_other");
  const refreshWorkMarkers = async () => {
    try {
      const r = await api.listWorkMarkers(areaCode);
      setWorkMarkers(r.markers);
    } catch (e) {
      notifyError(e);
    }
  };
  useEffect(() => { if (me) refreshWorkMarkers(); }, [areaCode, me]);
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
          if (s.route_geometry || s.route_geometry_unmarked) {
            routeItems.push({
              rutenummer: s.rutenummer,
              rutenavn: s.rutenavn ?? null,
              route_geometry: s.route_geometry,
              route_geometry_unmarked: s.route_geometry_unmarked,
            });
          }
        }
        setRoutes(routeItems);
        setRouteSummaries(m);
      })
      .catch((e) => { if (!cancelled) notifyError(e, "Klarte ikke å laste området"); })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [areaCode, me, areaReloadKey]);

  const refreshCandidates = async (): Promise<CandidatesResponse | null> => {
    try {
      const c = await api.getCandidates(areaCode);
      setCandidates(c);
      return c;
    } catch (e) {
      notifyError(e);
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
    if (sidebarTab === "grunneier" && grunneierMode === "ruter") {
      // Grunneier "Ruter" mode — clicking a rendered route line toggles it into
      // the owner-lookup selection. routesAtPoint is the rutenumre under the
      // click; pick the first when several overlap. A miss (no route) is a
      // no-op so empty-map clicks don't clear the selection.
      if (routesAtPoint.length > 0) toggleRouteSelection(routesAtPoint[0]);
      return;
    }
    if (sidebarTab === "grunneier" && grunneierMode === "punkt") {
      // Grunneier "Punkt" mode owns map clicks — clicking anywhere fetches
      // the matrikkelenhet containing the point. In "Ruter" mode the click
      // toggles route selection instead (branch above).
      setMatrikkelLoading(true);
      setMatrikkelError(null);
      try {
        const r = await api.pointMatrikkelenhet(lat, lon);
        setMatrikkelResult(r);
      } catch (e) {
        // 404 from the backend means "no matrikkelenhet at this point"
        // (sea, glacier, etc.) — distinct from a network/auth error.
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("404")) {
          setMatrikkelResult(null);
          setMatrikkelError("Ingen matrikkelenhet på dette punktet.");
        } else {
          notifyError(e);
          setMatrikkelError(msg);
        }
      } finally {
        setMatrikkelLoading(false);
      }
      return;
    }
    if (mode === "place-photo") {
      // Geotag the picked-pending photo at the clicked position, then exit.
      if (pendingPlacementId == null) { setMode("browse"); return; }
      try {
        await api.patchPhoto(pendingPlacementId, { lon, lat });
        setPendingPlacementId(null);
        setMode("browse");
        await refreshPhotos();
      } catch (e) {
        notifyError(e);
      }
      return;
    }
    if (mode === "place-work-marker") {
      // Drop a marker of the currently-armed kind on the focused route. The
      // kind is set by the Arbeid sub-tab buttons (or defaults to work_other
      // when the user enters the mode via the toolbar).
      if (!focusedRoute) { setMode("browse"); return; }
      try {
        await api.createRouteAnnotation(areaCode, focusedRoute, {
          kind: pendingWorkKind,
          title: null,
          lon,
          lat,
        });
        setMode("browse");
        setPendingWorkKind("work_other");
        await refreshWorkMarkers();
        setAnnotationsBumpKey((k) => k + 1);  // RoutePanel re-fetches its list
        setSidebarTab("rute");
      } catch (e) {
        notifyError(e);
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
      if (!nearest) { notifyError("Fant ingen rute nær klikket"); return; }
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
      notifyError(e);
    }
  }

  if (authChecking) {
    return (
      <Center mih="100vh">
        <Stack gap="sm" align="center">
          <Loader />
          <Text size="sm" c="dimmed">Sjekker innlogging…</Text>
        </Stack>
      </Center>
    );
  }
  if (!me) {
    return <LoginScreen errorCode={loginErrorCode} />;
  }

  const statLabel = candidates
    ? `${candidates.totals.total_sites} steder · ${candidates.totals.accepted} aksept · ${candidates.totals.rejected ?? 0} avvist`
    : loading
      ? "Laster…"
      : "";

  return (
    <div className="app">
      <Group className="topbar" bg="brand.7" px="md" gap="sm" wrap="nowrap" h={48}>
        <Text fw={600} c="white" size="sm" style={{ whiteSpace: "nowrap" }}>Skiltverktøy</Text>
        <Select
          value={areaCode}
          onChange={(v) => v && setAreaCode(v)}
          data={[
            { value: "bre", label: "Breheimen og Jostedalsbreen" },
            { value: "fem", label: "Femundsmarka" },
            { value: "ron", label: "Rondane" },
          ]}
          size="xs"
          allowDeselect={false}
          w={240}
        />
        <SearchBox onSelect={handleSearchSelect} />
        <div style={{ flex: 1 }} />
        {statLabel && (
          <Text size="xs" c="white" opacity={0.85} style={{ whiteSpace: "nowrap" }}>
            {statLabel}
          </Text>
        )}
        <Select
          value={baseLayer}
          onChange={(v) => v && setBaseLayer(v as BaseLayerId)}
          data={(Object.keys(BASE_LAYER_LABELS) as BaseLayerId[]).map((k) => ({
            value: k,
            label: BASE_LAYER_LABELS[k],
          }))}
          size="xs"
          allowDeselect={false}
          aria-label="Bakgrunnskart"
          w={180}
        />
        <Group gap="xs" wrap="nowrap" title={me.email}>
          {me.picture && <Avatar src={me.picture} size="sm" radius="xl" />}
          <Text size="xs" c="white" opacity={0.85} style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {me.email}
          </Text>
          <Button
            variant="default"
            size="xs"
            onClick={() => api.logout().catch((e) => notifyError(e))}
            title="Logg ut"
          >
            Logg ut
          </Button>
        </Group>
      </Group>

      <div className="map-pane">
        <FloatingToolbar
          mode={mode}
          onChangeMode={(m) => {
            // Leaving place-photo via the toolbar should also clear the
            // pending pick so we don't enter a confusing half-state where
            // the panel says "armed" but no mode listens for clicks.
            if (mode === "place-photo" && m !== "place-photo") {
              setPendingPlacementId(null);
            }
            setMode(m);
          }}
          pendingPlacementId={pendingPlacementId}
          focusedRoute={focusedRoute}
        />
        <MapView
          routes={routes}
          routeSummaries={routeSummaries}
          sites={candidates?.sites ?? []}
          selectedIdx={selectedSiteIdx}
          onSelect={selectSiteByIdx}
          onMapClick={(mode === "add-manual" || mode === "place-photo" || mode === "place-work-marker" || sidebarTab === "grunneier") ? handleMapClick : undefined}
          cursor={(mode === "add-manual" || mode === "place-photo" || mode === "place-work-marker" || (sidebarTab === "grunneier" && grunneierMode === "punkt")) ? "crosshair" : undefined}
          placementActive={mode === "add-manual" || mode === "place-photo" || mode === "place-work-marker" || sidebarTab === "grunneier"}
          matrikkelPolygon={matrikkelResult?.polygon_geometry ?? null}
          selectedRoutes={selectedRoutes}
          highlightGeometry={highlightGeometry}
          flyTo={flyTo}
          kulturminner={kulturminnerFC}
          hoveredKulturminneId={hoveredKulturminneId}
          baseLayer={baseLayer}
          focusedRoute={focusedRoute}
          onFocusRoute={setFocusedRoute}
          areaCode={areaCode}
          photos={placedPhotos}
          photosVisible={photosVisible}
          onPhotosVisibleChange={setPhotosVisible}
          onPhotosOpen={handleMapPhotosOpen}
          workMarkers={workMarkers}
          workMarkersVisible={workMarkersVisible}
          hoveredAnnotationId={hoveredAnnotationId}
          onWorkMarkersVisibleChange={setWorkMarkersVisible}
          onWorkMarkerOpen={(annotationId) => {
            const m = workMarkers.find((w) => w.id === annotationId);
            if (m) {
              setFocusedRoute(m.rutenummer);
              setSidebarTab("rute");
            }
          }}
          loopArms={loopArms}
          gpxTracks={gpxTracks}
          gpxVisible={gpxVisible}
          onGpxVisibleChange={setGpxVisible}
        />
      </div>

      <Tabs
        value={sidebarTab}
        onChange={(v) => v && setSidebarTab(v as SidebarTab)}
        className="side"
        variant="default"
        keepMounted={false}
      >
        <Tabs.List grow>
          <Tabs.Tab value="sites" leftSection={<IconMapPin size={14} />}>
            Skiltsteder
          </Tabs.Tab>
          <Tabs.Tab
            value="rute"
            leftSection={<IconRoute size={14} />}
            rightSection={focusedRoute ? <Badge size="xs" color="brand" variant="light">{focusedRoute}</Badge> : null}
          >
            Rute
          </Tabs.Tab>
          <Tabs.Tab value="kvalitet" leftSection={<IconAlertTriangle size={14} />}>
            Kvalitet
          </Tabs.Tab>
          <Tabs.Tab
            value="photos"
            leftSection={<IconCamera size={14} />}
            rightSection={pendingPhotos.length > 0
              ? <Badge size="xs" color="orange" circle>{pendingPhotos.length}</Badge>
              : null}
          >
            Bilder
          </Tabs.Tab>
          <Tabs.Tab
            value="spor"
            leftSection={<IconRoute2 size={14} />}
            rightSection={
              gpxLoading
                ? <Loader size="xs" />
                : gpxTracks.length > 0
                  ? <Badge size="xs" color="blue" variant="light">{gpxTracks.length}</Badge>
                  : null
            }
          >
            Spor
          </Tabs.Tab>
          <Tabs.Tab
            value="export"
            leftSection={<IconDownload size={14} />}
            rightSection={selectedPanels.size > 0
              ? <Badge size="xs" color="brand" circle>{selectedPanels.size}</Badge>
              : null}
          >
            Eksport
          </Tabs.Tab>
          {me?.features?.includes("grunneier") && (
            <Tabs.Tab value="grunneier" leftSection={<IconHomeDollar size={14} />}>
              Grunneier
            </Tabs.Tab>
          )}
          <Tabs.Tab value="about" leftSection={<IconInfoCircle size={14} />}>
            Om
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="sites" className="side-panel">
          {!selectedSite && (
            <Text c="dimmed" size="sm" p="lg" ta="center">
              {mode === "add-manual"
                ? "Klikk på kartet langs en rute for å plassere et manuelt skilt. Felles segment blir automatisk knyttet til alle rutene der."
                : mode === "place-photo"
                  ? "Klikk på kartet for å plassere det valgte bildet."
                  : loading
                    ? "Laster skiltsteder…"
                    : "Velg et skiltsted på kartet."}
            </Text>
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
        </Tabs.Panel>

        <Tabs.Panel value="rute" className="side-panel">
          {!focusedRoute && (
            <Text c="dimmed" size="sm" p="lg" ta="center">
              Velg en rute på kartet for å se rutebok, inspeksjoner, dugnader og arbeidsbehov.
            </Text>
          )}
          {focusedRoute && (
            <RoutePanel
              areaCode={areaCode}
              rutenummer={focusedRoute}
              routeSummary={routeSummaries.get(focusedRoute)}
              onClose={() => setFocusedRoute(null)}
              onChanged={refreshWorkMarkers}
              onArmPlaceWorkMarker={(kind) => {
                setPendingWorkKind(kind);
                setMode("place-work-marker");
              }}
              placeWorkMarkerArmed={mode === "place-work-marker"}
              armedWorkKind={mode === "place-work-marker" ? pendingWorkKind : null}
              onLoopArmsChange={setLoopArms}
              onRouteShapeChanged={() => setAreaReloadKey((k) => k + 1)}
              initialSubTab={routeInitialSubTab}
              onInitialSubTabConsumed={() => setRouteInitialSubTab(null)}
              refreshKey={annotationsBumpKey}
              onOpenPhotos={(photos, index) => setLightboxState({ photos, index })}
              onHoverAnnotation={setHoveredAnnotationId}
              onHoverKulturminne={setHoveredKulturminneId}
            />
          )}
        </Tabs.Panel>

        <Tabs.Panel value="kvalitet" className="side-panel">
          <AreaValidationPanel
            areaCode={areaCode}
            onOpenRoute={(rn) => {
              setFocusedRoute(rn);
              setRouteInitialSubTab("validation");
              setSidebarTab("rute");
            }}
          />
        </Tabs.Panel>

        <Tabs.Panel value="photos" className="side-panel">
          <PhotoPanel
            areaCode={areaCode}
            placed={placedPhotos}
            pending={pendingPhotos}
            selectedPendingId={pendingPlacementId}
            placementArmed={mode === "place-photo"}
            onPickPendingForPlacement={pickPendingForPlacement}
            onClose={() => setSidebarTab("sites")}
            onChanged={refreshPhotos}
            onOpenLightbox={openLightbox}
          />
        </Tabs.Panel>

        <Tabs.Panel value="spor" className="side-panel">
          <GpxPanel
            areaCode={areaCode}
            tracks={gpxTracks}
            loading={gpxLoading}
            onUpload={handleUploadGpx}
            onDelete={handleDeleteGpx}
          />
        </Tabs.Panel>

        <Tabs.Panel value="export" className="side-panel">
          <ExportTab
            areaCode={areaCode}
            selectedPanels={selectedPanels}
            onClearSelection={clearPanelSelection}
          />
        </Tabs.Panel>

        {me?.features?.includes("grunneier") && (
          <Tabs.Panel value="grunneier" className="side-panel">
            <GrunneierPanel
              mode={grunneierMode}
              onModeChange={setGrunneierMode}
              result={matrikkelResult}
              loading={matrikkelLoading}
              error={matrikkelError}
              onClear={() => { setMatrikkelResult(null); setMatrikkelError(null); }}
              selectedRutenumre={selectedRoutes}
              routeOwners={routeOwners}
              routeOwnersLoading={routeOwnersLoading}
              routeOwnersError={routeOwnersError}
              onFetchRouteOwners={fetchRouteOwners}
              onClearRoutes={clearRouteSelection}
              onHoverMatrikkel={setHighlightGeometry}
              onExportRouteOwners={exportRouteOwners}
              exporting={routeOwnersExporting}
            />
          </Tabs.Panel>
        )}

        <Tabs.Panel value="about" className="side-panel">
          <AreaReport
            areaCode={areaCode}
            candidates={candidates}
            routeSummaries={routeSummaries}
            onSelectRoute={(rn) => {
              setFocusedRoute(rn);
              setSidebarTab("rute");
            }}
          />
        </Tabs.Panel>
      </Tabs>

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
