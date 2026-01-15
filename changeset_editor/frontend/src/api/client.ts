/** API client for changeset editor */
import type {
  Changeset,
  ChangeEvent,
  EventPayload,
  ValidationResponse,
  SnapTarget,
  RouteResponse,
  RoutesResponse,
  RouteSegmentsResponse,
  RouteLinksResponse,
  RouteValidationResponse,
  RouteInfo,
} from '../types';
import { isRetryableError } from '../utils/errorHandler';

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

export const isAbortError = (error: unknown): boolean => {
  if (!error || typeof error !== 'object') {
    return false;
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    return true;
  }
  return 'name' in error && (error as { name?: string }).name === 'AbortError';
};

export async function requestWithAbort<T>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<T> {
  try {
    return await request<T>(endpoint, options);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw error;
  }
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
    requestWithAbort<Changeset>('/changesets', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getChangeset: (id: string): Promise<Changeset> =>
    requestWithAbort<Changeset>(`/changesets/${id}`),

  listChangesets: (limit = 100, offset = 0): Promise<Changeset[]> =>
    requestWithAbort<Changeset[]>(`/changesets?limit=${limit}&offset=${offset}`),

  // Events
  addEvent: (changesetId: string, event: EventPayload): Promise<ChangeEvent> =>
    requestWithAbort<ChangeEvent>(`/changesets/${changesetId}/events`, {
      method: 'POST',
      body: JSON.stringify({ event }),
    }),

  getEvents: (changesetId: string): Promise<{ events: ChangeEvent[] }> =>
    requestWithAbort<{ events: ChangeEvent[] }>(`/changesets/${changesetId}/events`),

  // Validation
  validate: (changesetId: string): Promise<ValidationResponse> =>
    requestWithAbort<ValidationResponse>(`/changesets/${changesetId}/validate`, {
      method: 'POST',
    }),

  // GeoJSON
  getDiffGeoJSON: (changesetId: string): Promise<GeoJSON.FeatureCollection> =>
    requestWithAbort<GeoJSON.FeatureCollection>(`/changesets/${changesetId}/diff.geojson`),

  getEffectiveGeoJSON: (
    changesetId: string
  ): Promise<GeoJSON.FeatureCollection> =>
    requestWithAbort<GeoJSON.FeatureCollection>(
      `/changesets/${changesetId}/effective.geojson`
    ),

  // Publish
  publish: (changesetId: string): Promise<{
    changeset_id: string;
    status: string;
    pr_url: string;
    artifacts: Record<string, string>;
  }> =>
    requestWithAbort(`/changesets/${changesetId}/publish`, {
      method: 'POST',
    }),

  // Snap targets
  getSnapTargets: (bbox: string): Promise<{ targets: SnapTarget[] }> =>
    requestWithAbort<{ targets: SnapTarget[] }>(`/snap-targets?bbox=${bbox}`),

  // Routes
  getRoute: (
    rutenummer: string,
    includeGeometry = false,
    options: RequestOptions = {}
  ): Promise<RouteResponse> =>
    requestWithAbort<RouteResponse>(
      `/v1/routes/${rutenummer}?include_geometry=${includeGeometry ? 'true' : 'false'}`,
      options
    ),

  listRoutes: (
    params: { limit?: number; prefix?: string } = {},
    options: RequestOptions = {}
  ): Promise<RoutesResponse> => {
    const query = new URLSearchParams();
    if (params.limit) query.set('limit', String(params.limit));
    if (params.prefix) query.set('prefix', params.prefix);
    const qs = query.toString();
    return requestWithAbort<RoutesResponse>(`/v1/routes${qs ? `?${qs}` : ''}`, options);
  },

  getRoutesInBbox: (
    bbox: string,
    options: RequestOptions = {}
  ): Promise<RoutesResponse> =>
    requestWithAbort<RoutesResponse>(
      `/v1/routes?bbox=${bbox}&include_geometry=true&limit=500`,
      options
    ),

  getRouteSegments: (
    rutenummer: string,
    includeGeometry = true,
    options: RequestOptions = {}
  ): Promise<RouteSegmentsResponse> =>
    requestWithAbort<RouteSegmentsResponse>(
      `/v1/routes/${rutenummer}/segments?include_geometry=${includeGeometry ? 'true' : 'false'}`,
      options
    ),

  getRouteLinks: (
    rutenummer: string,
    includeGeometry = true,
    options: RequestOptions = {}
  ): Promise<RouteLinksResponse> =>
    requestWithAbort<RouteLinksResponse>(
      `/v1/routes/${rutenummer}/links?include_geometry=${includeGeometry ? 'true' : 'false'}`,
      options
    ),

  validateRoute: (
    rutenummer: string,
    options: RequestOptions = {}
  ): Promise<RouteValidationResponse> =>
    requestWithAbort<RouteValidationResponse>(`/v1/routes/${rutenummer}/validate`, options),

  searchPlaces: (
    query: string,
    limit = 20,
    options: RequestOptions = {}
  ): Promise<{ results: RouteInfo[] }> =>
    requestWithAbort<{ results: RouteInfo[] }>(
      `/v1/search/places?q=${encodeURIComponent(query)}&limit=${limit}`,
      options
    ),
};
