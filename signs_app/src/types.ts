export type SignColor = "trehvit" | "grønn";
export type SignStatus = "proposed" | "accepted" | "rejected" | "installed";

export interface SessionUser {
  email: string;
  name: string;
  picture: string | null;
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
  | "work_other";

export const ROUTE_ANNOTATION_KINDS: RouteAnnotationKind[] = [
  "diary",
  "inspection",
  "dugnad",
  "work_klipping",
  "work_bridge",
  "work_klopper",
  "work_other",
];

export const ROUTE_ANNOTATION_KIND_LABEL_NB: Record<RouteAnnotationKind, string> = {
  diary: "Dagbok",
  inspection: "Inspeksjon",
  dugnad: "Dugnad",
  work_klipping: "Klipping",
  work_bridge: "Bro",
  work_klopper: "Klopper",
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
