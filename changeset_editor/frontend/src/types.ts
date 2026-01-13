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
  patch: Array<{ op: 'replace' | 'add' | 'remove'; path: string; value?: any }>;
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
  attrs: Record<string, any>;
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

export interface SnapTarget {
  id: string;
  geometry: GeoJSON.LineString;
  vertices: number[][];
}
