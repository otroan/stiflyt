export type SignColor = "trehvit" | "grønn";
export type SignStatus = "proposed" | "accepted" | "rejected" | "installed";

/** One matrikkelenhet (cadastral unit) returned by POST /point/matrikkelenhet.
 *  `polygon_geometry` is GeoJSON Polygon in WGS84 — rendered as the highlight
 *  layer in the Grunneier tab. `owners` is a server-formatted multi-line
 *  string (one line per ejer); rendered as `<pre>` to preserve newlines. */
export interface PointMatrikkelResponse {
  matrikkelenhet: string;
  matrikkelnummertekst?: string | null;
  bruksnavn?: string | null;
  kommunenummer?: number | null;
  kommunenavn?: string | null;
  arealmerknadtekst?: string | null;
  lagretberegnetareal?: number | null;
  gardsnummer?: number | null;
  bruksnummer?: number | null;
  festenummer?: number | null;
  polygon_geometry: GeoJSON.Polygon;
  owners?: string | null;
  owner_error?: string | null;
  teigid?: number | null;
}

/** One property intersection from POST /geometry/owners. `owners` is the same
 *  server-formatted string used by PointMatrikkelResponse — "Navn, Adresse;
 *  Navn2, Adresse2". Mirrors the route-owner vector. */
export interface GeometryOwnerItem {
  matrikkelenhet: string;
  matrikkelnummertekst?: string | null;
  bruksnavn?: string | null;
  kommunenummer?: number | null;
  kommunenavn?: string | null;
  gardsnummer?: number | null;
  bruksnummer?: number | null;
  festenummer?: number | null;
  offset_meters?: number | null;
  length_km?: number | null;
  owners?: string | null;
  /** The portion of the link line that falls inside this matrikkelenhet, in
   *  WGS84. Used to highlight the segment on the map when its owner row is
   *  hovered. */
  geometry?: GeoJSON.Geometry | null;
}

export interface GeometryOwnerResponse {
  geometry: GeoJSON.Geometry;
  total_length_meters: number;
  total_length_km: number;
  matrikkelenhet_vector: GeometryOwnerItem[];
  error_summary?: string | null;
}

/** A hit from GET /search/places — combined search over ruteinfopunkt
 *  (rutepunkt), stedsnavn and ruter. `lon`/`lat` are WGS84 for map fly-to;
 *  `rutenummer` is set on `rute` hits so we can also focus the route. */
export interface PlaceSearchResult {
  id: string;
  type: "ruteinfopunkt" | "stedsnavn" | "rute";
  title: string;
  subtitle?: string | null;
  lon: number;
  lat: number;
  rutenummer?: string | null;
}

export interface PlaceSearchResponse {
  results: PlaceSearchResult[];
  total: number;
}

/** A cultural-heritage monument (Riksantikvaren Askeladden) near a route, from
 *  GET /routes/{rutenummer}/kulturminner. `link` opens it in Kulturminnesøk. */
export interface Kulturminne {
  kulturminneid: string | null;
  navn: string | null;
  kategori: string | null;
  art: string | null;
  datering: string | null;
  vernetype: string | null;
  link: string | null;
  distance_m: number | null;
  lon: number | null;
  lat: number | null;
  geometry?: GeoJSON.Geometry | null;
}

export interface RouteKulturminnerResponse {
  rutenummer: string;
  radius_m: number;
  /** False when the kulturminner dataset hasn't been imported into the DB. */
  available: boolean;
  count: number;
  kulturminner: Kulturminne[];
}

/** A named, routable anchor node from /signs/area/{area}/anchors/search —
 *  a candidate destination for a manually-added "through" sign. */
export interface AnchorHit {
  anchor_node_id: number;
  name: string;
  lon: number | null;
  lat: number | null;
  source?: string;
}

/** Result of /signs/area/{area}/distance — the Dijkstra walking distance to a
 *  destination anchor over the cross-area DNT-route graph. `routes` is the
 *  minimal continuous route sequence, e.g. ["bre1","bre3"] → "via bre1, bre3".
 *  `distance_meters` already includes the per-area correction factor. */
export interface ThroughDistance {
  found: boolean;
  from_node: number | null;
  raw_meters?: number;
  correction_factor?: number;
  distance_meters: number | null;
  routes: string[];
}

export interface SessionUser {
  email: string;
  name: string;
  picture: string | null;
  /** Feature flags granted to this user (e.g. "signs", "grunneier"). Drives
   *  conditional UI — the Grunneier tab/section only mounts when this list
   *  contains "grunneier". Sorted server-side for deterministic equality. */
  features: string[];
}

export interface SignPanel {
  destination_name: string;
  destination_anchor_node_id: number | null;
  /** Physical out-link from the sign anchor that this panel covers. Two
   *  panels with the same destination but different first_link_id are
   *  parallel-path siblings (e.g. bre21 vs bre62 to Arentzbu) and edit
   *  independently. */
  first_link_id?: number | null;
  route_numbers: string[];
  distance_m_db: number | null;
  distance_km_displayed: number | null;
  color: SignColor;
  direction?: string | null;
  /** Manually-added "through" destination (beyond this route's endpoint, maybe
   *  cross-area). `via_routes` is the DNT-route path to it ("via bre1, bre3"). */
  is_manual_through?: boolean;
  via_routes?: string[];
}

export interface ForeignRouteGroup {
  owner_area: string | null;
  route_numbers: string[];
}

export interface SignSite {
  sign_site_id: number | null;
  site_code: string | null;
  anchor_node_id: number | null;
  lon: number | null;
  lat: number | null;
  name: string | null;
  status: SignStatus;
  is_endpoint: boolean;
  is_junction: boolean;
  is_cross_area?: boolean;
  is_manual?: boolean;
  rutenummer?: string | null;
  route_numbers: string[];
  foreign_route_numbers?: string[];
  foreign_route_groups?: ForeignRouteGroup[];
  back_text: string;
  utm_coords: string | null;
  panels: SignPanel[];
}

export interface CandidatesResponse {
  area_code: string;
  sites: SignSite[];
  totals: {
    total_sites: number;
    proposed: number;
    accepted: number;
    rejected?: number;
    installed?: number;
  };
  scope: { prefix?: string; routes?: string[] };
}

export interface PlacenameCandidate {
  name: string;
  source_type: "ruteinfopunkt" | "stedsnavn" | "anchor_node" | string;
  source_id?: string | null;
  distance_meters?: number | null;
  tilrettelegging?: string | null;
}

export interface FacilityCandidate {
  name: string;
  source_id?: string | null;
  distance_meters?: number | null;
  tilrettelegging?: string | null;
}

export interface PlacenameCandidatesResponse {
  anchor_node_id: number;
  radius_meters: number;
  candidates: PlacenameCandidate[];
  facilities: FacilityCandidate[];
}

export interface RouteSummary {
  rutenummer: string;
  rutenavn?: string | null;
  start_anchor_node_id: number | null;
  end_anchor_node_id: number | null;
  start_name: string | null;
  end_name: string | null;
  length_m: number;
  length_km_displayed: number | null;
  /** True when the route's link graph splits into >1 component, so the
   *  endpoint pair is unreliable and along-route distances can't span the gap.
   *  See RouteDisconnectedValidator / the Validering tab. */
  disconnected?: boolean;
  /** Cached elevation results (null until the route's profile is resolved via
   *  the Høyde tab). Drives the Naismith hiking-time estimate. */
  length_3d_m?: number | null;
  ascent_m?: number | null;
  /** GeoJSON MultiLineString (WGS84) of the marked / walkable portion. */
  route_geometry?: GeoJSON.Geometry | null;
  /** GeoJSON MultiLineString of unmarked portions (boat / glacier).
   *  Rendered as a dashed line so the safety annotation on the panel
   *  ("via båt", "via bre") has a visual companion on the map. */
  route_geometry_unmarked?: GeoJSON.Geometry | null;
}

export interface AreaRouteSummaryResponse {
  area_code: string;
  routes: RouteSummary[];
}

export interface RouteListItem {
  rutenummer: string;
  rutenavn?: string | null;
  route_geometry?: GeoJSON.Geometry | null;
  route_geometry_unmarked?: GeoJSON.Geometry | null;
}

export type FieldPhotoTag =
  | "sign"
  | "panel"
  | "signpost"
  | "route-condition"
  | "damage"
  | "bridge"
  | "cairn"
  | "general";

export const FIELD_PHOTO_TAGS: FieldPhotoTag[] = [
  "sign",
  "panel",
  "signpost",
  "route-condition",
  "damage",
  "bridge",
  "cairn",
  "general",
];

export interface FieldPhoto {
  id: number;
  area_code: string;
  lon: number | null;
  lat: number | null;
  thumb_url: string;
  display_url: string;
  original_url: string;
  mime_type: string | null;
  bytes: number | null;
  taken_at: string | null;
  exif_heading_deg: number | null;
  tags: FieldPhotoTag[];
  caption: string | null;
  uploaded_at: string | null;
  uploaded_by: string | null;
  needs_placement: boolean;
}

export interface FieldPhotosResponse {
  area_code: string;
  photos: FieldPhoto[];
  count: number;
}

export interface AreaStatsResponse {
  area_code: string;
  total_routes: number;
  unique_trail_length_m: number;
  unique_trail_length_km_displayed: number;
  distance_correction_factor: number;
}

export type RouteAnnotationKind =
  | "diary"
  | "inspection"
  | "dugnad"
  | "work_klipping"
  | "work_bridge"
  | "work_klopper"
  | "work_skilt"
  | "work_other";

export const ROUTE_ANNOTATION_KINDS: RouteAnnotationKind[] = [
  "diary",
  "inspection",
  "dugnad",
  "work_klipping",
  "work_bridge",
  "work_klopper",
  "work_skilt",
  "work_other",
];

export const ROUTE_ANNOTATION_KIND_LABEL_NB: Record<RouteAnnotationKind, string> = {
  diary: "Dagbok",
  inspection: "Inspeksjon",
  dugnad: "Dugnad",
  work_klipping: "Klipping",
  work_bridge: "Bro",
  work_klopper: "Klopper",
  work_skilt: "Skilt",
  work_other: "Annet arbeid",
};

export interface RouteAnnotation {
  id: number;
  area_code: string;
  rutenummer: string;
  kind: RouteAnnotationKind;
  position_along_m: number | null;
  title: string | null;
  body: string | null;
  occurred_at: string | null;
  recorded_by: string | null;
  created_at: string | null;
  resolved_at: string | null;
  lon: number | null;
  lat: number | null;
}

export interface RouteAnnotationsResponse {
  area_code: string;
  rutenummer: string;
  annotations: RouteAnnotation[];
}

export interface WorkMarkersResponse {
  area_code: string;
  markers: RouteAnnotation[];
}

// --- Route validation + link-exclusion correction ---

export type ValidationSeverity = "error" | "warning" | "info";

export interface LoopArm {
  links: number[];
  nodes: number[];
  length_m: number;
  geometry?: GeoJSON.Geometry | null;
}

export interface LoopArmGroup {
  endpoints: number[];
  arms: LoopArm[];
}

export interface RouteComponent {
  nodes: number[];
  endpoints: number[];
}

export interface BridgeSuggestion {
  a_node: number;
  b_node: number;
  gap_m: number;
}

/** One validator finding. Validator metadata is merged in at the top level
 *  (see ValidationIssue.to_dict on the backend), so loop-specific fields like
 *  `arm_groups` ride alongside the common ones. */
export interface ValidationIssue {
  type: string;
  message: string;
  severity: ValidationSeverity;
  affected_links?: number[];
  affected_segments?: string[];
  // ROUTE_HAS_LOOP extras:
  cyclomatic?: number;
  fork_nodes?: number[];
  arm_groups?: LoopArmGroup[];
  decomposable?: boolean;
  // ROUTE_DISCONNECTED extras:
  component_count?: number;
  components?: RouteComponent[];
  bridge_suggestions?: BridgeSuggestion[];
  [key: string]: unknown;
}

export interface RouteValidationResponse {
  area_code: string;
  rutenummer: string;
  status: "ERROR" | "WARNING" | "OK";
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  info: ValidationIssue[];
}

export interface LinkExclusion {
  rutenummer: string;
  link_id: number;
  reason: string | null;
  comment: string | null;
  reported_at: string | null;
  updated_by: string | null;
  updated_at: string | null;
}

export interface LinkExclusionsResponse {
  area_code: string;
  rutenummer: string;
  exclusions: LinkExclusion[];
}

export interface LinkBridge {
  rutenummer: string;
  a_node: number;
  b_node: number;
  reason: string | null;
  comment: string | null;
  reported_at: string | null;
  updated_by: string | null;
  updated_at: string | null;
}

export interface LinkBridgesResponse {
  area_code: string;
  rutenummer: string;
  bridges: LinkBridge[];
}

export interface AreaValidationRoute {
  rutenummer: string;
  rutenavn: string | null;
  vedlikeholdsansvarlig: string | null;
  status: "ERROR" | "WARNING" | "OK";
  errors: number;
  warnings: number;
  info: number;
  issue_types: string[];
}

export interface AreaValidationResponse {
  area_code: string;
  status: "computing" | "ready" | "error";
  computed_at: string | null;
  compute_seconds?: number;
  error?: string;
  routes: AreaValidationRoute[];
}

export interface MetadataOverride {
  rutenummer: string;
  rutenavn: string | null;
  vedlikeholdsansvarlig: string | null;
  rutetype: string | null;
  gradering: string | null;
  comment: string | null;
  reported_at: string | null;
  updated_by: string | null;
  updated_at: string | null;
}

export interface MetadataOverrideResponse {
  area_code: string;
  rutenummer: string;
  override: MetadataOverride | null;
}

export interface GpxTrack {
  id: number;
  area_code: string;
  name: string | null;
  point_count: number | null;
  length_m: number | null;
  length_km: number | null;
  uploaded_by: string | null;
  uploaded_at: string | null;
  geometry: GeoJSON.Geometry | null;
}

export interface GpxTracksResponse {
  area_code: string;
  tracks: GpxTrack[];
}

export interface GpxComparisonTrack {
  track_id: number;
  name: string | null;
  walked_m: number;
  route_covered_m: number;
  coverage_pct: number | null;
  factor: number | null;
}

export interface GpxComparison {
  area_code: string;
  rutenummer: string;
  route_len_m: number | null;
  corridor_m: number;
  tracks: GpxComparisonTrack[];
  measured_factor: number | null;
  n_tracks_used: number;
  assumed_factor: number;
}

export interface ElevationProfile {
  area_code: string;
  rutenummer: string;
  samples: [number, number | null][]; // [distance_along_m, elevation_m]
  point_count: number | null;
  length_2d_m: number | null;
  length_3d_m: number | null;
  ascent_m: number | null;
  descent_m: number | null;
  min_z: number | null;
  max_z: number | null;
  datakilde: string | null;
  sampled_at: string | null;
  cached: boolean;
  /** Name of the anchor at the first sampled vertex (x=0 on the chart). */
  start_name: string | null;
  /** Name of the anchor at the last sampled vertex (x=length on the chart). */
  end_name: string | null;
}
