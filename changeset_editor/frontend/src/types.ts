/** Type definitions for changeset editor */
import type { GeoJSON } from 'geojson';

export interface Changeset {
  id: string;
  title: string;
  description?: string;
  area?: string;
  status: 'draft' | 'review' | 'approved' | 'exported';
  created_by: string;
  created_at: string;
  updated_at: string;
  base_snapshot: string;
  linked_issue_url?: string;
  pr_url?: string;
}

export interface ChangeEvent {
  event_id: string;
  changeset_id: string;
  ts: string;
  user_id: string;
  event: EventPayload;
}

export type EventPayload =
  | SegmentUpdateAttrsEvent
  | SegmentUpdateGeomEvent
  | SegmentRetireEvent
  | SegmentAddEvent
  | SegmentDeleteNewEvent;

export interface SegmentUpdateAttrsEvent {
  type: 'segment.update_attrs';
  target: { kind: 'segment'; id: string };
  patch: Array<{ op: 'replace' | 'add' | 'remove'; path: string; value?: unknown }>;
  comment?: string;
}

export interface SegmentUpdateGeomEvent {
  type: 'segment.update_geom';
  target: { kind: 'segment'; id: string };
  geometry: GeoJSON.LineString;
  srid: number;
  comment?: string;
}

export interface SegmentRetireEvent {
  type: 'segment.retire';
  target: { kind: 'segment'; id: string };
  comment?: string;
}

export interface SegmentAddEvent {
  type: 'segment.add';
  temp_id: string;
  geometry: GeoJSON.LineString;
  srid: number;
  attrs: Record<string, unknown>;
  comment?: string;
}

export interface SegmentDeleteNewEvent {
  type: 'segment.delete_new';
  target: { kind: 'segment'; temp_id: string };
  comment?: string;
}

export interface ValidationIssue {
  severity: 'error' | 'warn';
  code: string;
  message: string;
  feature_ref: { kind: string; id: string };
  location?: { lon: number; lat: number };
}

export interface ValidationResponse {
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

// Route validation types (from /api/v1/routes/{rutenummer}/validate)
export interface RouteValidationIssue {
  type: string;
  message: string;
  severity: 'error' | 'warning' | 'info';
  affected_segments?: string[] | null;
  affected_links?: number[] | null;
  metadata?: Record<string, unknown> | null;
}

export interface RouteValidationSummary {
  total_segments: number;
  total_fotruteinfo_rows: number;
  total_links: number;
  error_count: number;
  warning_count: number;
  geometry_error_count: number;
  geometry_warning_count: number;
  rutenavn_values?: string[] | null;
  vedlikeholdsansvarlig_values?: string[] | null;
  rutetype_values?: string[] | null;
  gradering_values?: string[] | null;
}

export interface RouteValidationResponse {
  rutenummer: string;
  segment_count: number;
  link_count: number;
  status: 'OK' | 'WARNING' | 'ERROR';
  errors: RouteValidationIssue[];
  warnings: RouteValidationIssue[];
  geometry_info: RouteValidationIssue[];
  segment_metadata: unknown[]; // SegmentMetadata[] - simplified for now
  summary: RouteValidationSummary;
}

export interface SnapTarget {
  id: string;
  geometry: GeoJSON.LineString;
  vertices: number[][];
}

// Route API Response Types
export interface RouteInfo {
  rutenummer: string;
  rutenavn: string | null;
  vedlikeholdsansvarlig: string | null;
  rutetype?: string | null;
}

export interface RouteResponse {
  rutenummer: string;
  rutenavn: string | null;
  vedlikeholdsansvarlig: string | null;
  rutetype?: string | null;
  route_geometry: GeoJSON.Geometry | null;
  total_length_m?: number;
  total_length_meters?: number;
  total_length_km?: number;
  segment_count?: number;
  segment_objids?: number[] | null;
  from_name?: string | null;
  to_name?: string | null;
}

export interface RoutesResponse {
  routes: (RouteInfo & { route_geometry?: GeoJSON.Geometry | null })[];
  total?: number;
}

export interface RouteSegment {
  objid?: number;
  segment_objid?: number;
  rutenummer: string;
  rutenavn?: string | null;
  vedlikeholdsansvarlig?: string | null;
  rutetype?: string | null;
  gradering?: string | null;
  geometry?: GeoJSON.Geometry | null;
  senterlinje?: GeoJSON.Geometry | null;
  length_meters?: number | null;
  length_m?: number | null;
  source_node?: number | null;
  target_node?: number | null;
}

export interface RouteSegmentsResponse {
  rutenummer: string;
  segments: RouteSegment[];
  total?: number;
}

export interface RouteLink {
  link_id: number;
  a_node: number | null;
  b_node: number | null;
  a_node_name?: string | null;
  b_node_name?: string | null;
  length_m?: number | null;
  length_meters?: number | null;
  segment_objids?: number[] | null;
  geom?: GeoJSON.Geometry | null;
  geometry?: GeoJSON.Geometry | null;
  senterlinje?: GeoJSON.Geometry | null;
}

export interface RouteLinksResponse {
  rutenummer: string;
  links: RouteLink[];
  total?: number;
}

export interface AnchorName {
  name: string;
  source_type: string;
  source_id?: string | null;
  distance_meters?: number | null;
  validated_by?: string | null;
  validated_at?: string | null;
}

export interface AnchorNodeInfo {
  anchor_node_id: number;
  coordinates: [number, number];
  link_count: number;
  name?: AnchorName | null;
}

export interface RouteAnchorsResponse {
  rutenummer: string;
  anchors: AnchorNodeInfo[];
  total: number;
}

export interface PlacenameCandidate {
  name: string;
  source_type: string;
  source_id?: string | null;
  distance_meters?: number | null;
  tilrettelegging?: string | null;
}

export interface PlacenameCandidatesResponse {
  anchor_node_id: number;
  radius_meters: number;
  candidates: PlacenameCandidate[];
}

export interface AnchorNameUpsertRequest {
  name: string;
  source_type: string;
  source_id?: string | null;
  distance_meters?: number | null;
  rutenummer?: string | null;
}

export interface AnchorNameUpsertResponse {
  anchor_node_id: number;
  rutenummer?: string | null;
  name: string;
  source_type: string;
  source_id?: string | null;
  distance_meters?: number | null;
  validated_by?: string | null;
  validated_at?: string | null;
}

// Local Event Type (before changeset is created)
export type LocalEvent = EventPayload;

// Type guards
export function isSegmentAddEvent(event: EventPayload): event is SegmentAddEvent {
  return event.type === 'segment.add';
}

export function isSegmentUpdateGeomEvent(event: EventPayload): event is SegmentUpdateGeomEvent {
  return event.type === 'segment.update_geom';
}

export function isSegmentUpdateAttrsEvent(event: EventPayload): event is SegmentUpdateAttrsEvent {
  return event.type === 'segment.update_attrs';
}

export function isSegmentRetireEvent(event: EventPayload): event is SegmentRetireEvent {
  return event.type === 'segment.retire';
}

export function isSegmentDeleteNewEvent(event: EventPayload): event is SegmentDeleteNewEvent {
  return event.type === 'segment.delete_new';
}

// Type guard for GeoJSON Geometry
export function isLineString(geometry: GeoJSON.Geometry): geometry is GeoJSON.LineString {
  return geometry.type === 'LineString';
}

export function isMultiLineString(geometry: GeoJSON.Geometry): geometry is GeoJSON.MultiLineString {
  return geometry.type === 'MultiLineString';
}

// Type guard for route response
export function isRouteResponse(data: unknown): data is RouteResponse {
  return (
    typeof data === 'object' &&
    data !== null &&
    'rutenummer' in data &&
    typeof (data as RouteResponse).rutenummer === 'string'
  );
}
