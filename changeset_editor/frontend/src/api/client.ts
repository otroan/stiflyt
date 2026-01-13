/** API client for changeset editor */
import type {
  Changeset,
  ChangeEvent,
  EventPayload,
  ValidationResponse,
  SnapTarget,
} from '../types';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const user = localStorage.getItem('user') || 'anonymous';
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-User': user,
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `HTTP ${response.status}: ${response.statusText}`);
  }

  return response.json();
}

export const api = {
  // Changesets
  createChangeset: (data: {
    title: string;
    description?: string;
    area?: string;
    linked_issue_url?: string;
    base_snapshot?: string;
  }): Promise<Changeset> =>
    request<Changeset>('/changesets', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getChangeset: (id: string): Promise<Changeset> =>
    request<Changeset>(`/changesets/${id}`),

  listChangesets: (limit = 100, offset = 0): Promise<Changeset[]> =>
    request<Changeset[]>(`/changesets?limit=${limit}&offset=${offset}`),

  // Events
  addEvent: (changesetId: string, event: EventPayload): Promise<ChangeEvent> =>
    request<ChangeEvent>(`/changesets/${changesetId}/events`, {
      method: 'POST',
      body: JSON.stringify({ event }),
    }),

  getEvents: (changesetId: string): Promise<{ events: ChangeEvent[] }> =>
    request<{ events: ChangeEvent[] }>(`/changesets/${changesetId}/events`),

  // Validation
  validate: (changesetId: string): Promise<ValidationResponse> =>
    request<ValidationResponse>(`/changesets/${changesetId}/validate`, {
      method: 'POST',
    }),

  // GeoJSON
  getDiffGeoJSON: (changesetId: string): Promise<GeoJSON.FeatureCollection> =>
    request<GeoJSON.FeatureCollection>(`/changesets/${changesetId}/diff.geojson`),

  getEffectiveGeoJSON: (
    changesetId: string
  ): Promise<GeoJSON.FeatureCollection> =>
    request<GeoJSON.FeatureCollection>(
      `/changesets/${changesetId}/effective.geojson`
    ),

  // Publish
  publish: (changesetId: string): Promise<{
    changeset_id: string;
    status: string;
    pr_url: string;
    artifacts: Record<string, string>;
  }> =>
    request(`/changesets/${changesetId}/publish`, {
      method: 'POST',
    }),

  // Snap targets
  getSnapTargets: (bbox: string): Promise<{ targets: SnapTarget[] }> =>
    request<{ targets: SnapTarget[] }>(`/snap-targets?bbox=${bbox}`),
};
