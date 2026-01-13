/** API client for changeset editor */
import type {
  Changeset,
  ChangeEvent,
  EventPayload,
  ValidationResponse,
  SnapTarget,
} from '../types';
import { handleApiError, isRetryableError, type AppError } from '../utils/errorHandler';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

interface RequestOptions extends RequestInit {
  retries?: number;
  retryDelay?: number;
}

/**
 * Request with automatic retry for retryable errors
 */
async function request<T>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<T> {
  const { retries = 3, retryDelay = 1000, ...fetchOptions } = options;
  const user = localStorage.getItem('user') || 'anonymous';

  let lastError: unknown;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const response = await fetch(`${API_BASE}${endpoint}`, {
        ...fetchOptions,
        headers: {
          'Content-Type': 'application/json',
          'X-User': user,
          ...fetchOptions.headers,
        },
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        const errorObj = {
          message: error.detail || `HTTP ${response.status}: ${response.statusText}`,
          statusCode: response.status,
          status: response.status,
        };
        
        // If retryable and not last attempt, retry
        if (isRetryableError(errorObj) && attempt < retries) {
          lastError = errorObj;
          await new Promise(resolve => setTimeout(resolve, retryDelay * (attempt + 1)));
          continue;
        }
        
        throw errorObj;
      }

      return response.json();
    } catch (error) {
      lastError = error;
      
      // If retryable and not last attempt, retry
      if (isRetryableError(error) && attempt < retries) {
        await new Promise(resolve => setTimeout(resolve, retryDelay * (attempt + 1)));
        continue;
      }
      
      // Last attempt or non-retryable error
      throw error;
    }
  }

  // This should never be reached, but TypeScript needs it
  throw lastError;
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
