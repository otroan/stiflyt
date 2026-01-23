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
  RouteAnchorsResponse,
  PlacenameCandidatesResponse,
  AnchorNameUpsertRequest,
  AnchorNameUpsertResponse,
  SignsReportResponse,
  SignsMissingReport,
  SignsProductionResponse,
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

function buildHeaders(headers?: HeadersInit): HeadersInit {
  const user = localStorage.getItem('user') || 'anonymous';
  return {
    'Content-Type': 'application/json',
    'X-User': user,
    ...headers,
  };
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

  downloadChangesetArtifact: async (
    changesetId: string,
    filename: string
  ): Promise<Blob> => {
    const response = await fetch(`${API_BASE}/changesets/${changesetId}/artifacts/${filename}`, {
      headers: buildHeaders(),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      const errorObj = {
        message: error.detail || `HTTP ${response.status}: ${response.statusText}`,
        statusCode: response.status,
        status: response.status,
      };
      throw errorObj;
    }
    return response.blob();
  },

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
      `/v1/routes?bbox=${bbox}&include_geometry=true&limit=1000`,
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

  getLinksByBbox: (
    bbox: { xmin: number; ymin: number; xmax: number; ymax: number },
    limit = 500,
    options: RequestOptions = {}
  ): Promise<GeoJSON.FeatureCollection> =>
    requestWithAbort<GeoJSON.FeatureCollection>(
      `/v1/links?bbox=${bbox.xmin},${bbox.ymin},${bbox.xmax},${bbox.ymax}&limit=${limit}`,
      options
    ),

  getRouteSigns: (
    rutenummer: string,
    options: RequestOptions = {}
  ): Promise<SignsReportResponse> =>
    requestWithAbort<SignsReportResponse>(`/v1/routes/${rutenummer}/signs`, options),

  getSignsByPrefix: (
    prefix: string,
    options: RequestOptions = {}
  ): Promise<SignsReportResponse> =>
    requestWithAbort<SignsReportResponse>(
      `/v1/signs?prefix=${encodeURIComponent(prefix)}`,
      options
    ),

  getSignsByBbox: (
    bbox: { xmin: number; ymin: number; xmax: number; ymax: number },
    options: RequestOptions = {}
  ): Promise<SignsReportResponse> =>
    requestWithAbort<SignsReportResponse>(
      `/v1/signs?bbox=${bbox.xmin},${bbox.ymin},${bbox.xmax},${bbox.ymax}`,
      options
    ),

  getSignsMissing: (
    prefix: string,
    options: RequestOptions = {}
  ): Promise<SignsMissingReport> =>
    requestWithAbort<SignsMissingReport>(
      `/v1/signs/missing?prefix=${encodeURIComponent(prefix)}`,
      options
    ),

  getSignsProductionByPrefix: (
    prefix: string,
    options: RequestOptions = {}
  ): Promise<SignsProductionResponse> =>
    requestWithAbort<SignsProductionResponse>(
      `/v1/signs/production?prefix=${encodeURIComponent(prefix)}`,
      options
    ),

  getRouteSignsProduction: (
    rutenummer: string,
    options: RequestOptions = {}
  ): Promise<SignsProductionResponse> =>
    requestWithAbort<SignsProductionResponse>(
      `/v1/routes/${rutenummer}/signs/production`,
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

  getRouteAnchors: (
    rutenummer: string,
    options: RequestOptions = {}
  ): Promise<RouteAnchorsResponse> =>
    requestWithAbort<RouteAnchorsResponse>(`/v1/routes/${rutenummer}/anchors`, options),

  getAnchorPlacenames: (
    anchorId: number,
    radius = 500,
    limit = 10,
    options: RequestOptions = {}
  ): Promise<PlacenameCandidatesResponse> =>
    requestWithAbort<PlacenameCandidatesResponse>(
      `/v1/anchors/${anchorId}/placenames?radius=${radius}&limit=${limit}`,
      options
    ),

  upsertAnchorName: (
    anchorId: number,
    payload: AnchorNameUpsertRequest,
    options: RequestOptions = {}
  ): Promise<AnchorNameUpsertResponse> =>
    requestWithAbort<AnchorNameUpsertResponse>(`/v1/anchors/${anchorId}/name`, {
      method: 'POST',
      body: JSON.stringify(payload),
      ...options,
    }),

  getAnchorsByBbox: (
    bbox: { xmin: number; ymin: number; xmax: number; ymax: number },
    limit = 500,
    options: RequestOptions = {}
  ): Promise<GeoJSON.FeatureCollection> =>
    requestWithAbort<GeoJSON.FeatureCollection>(
      `/v1/anchor-nodes?bbox=${bbox.xmin},${bbox.ymin},${bbox.xmax},${bbox.ymax}&limit=${limit}`,
      options
    ),

  getGeometryOwners: (
    geometry: GeoJSON.LineString,
    options: RequestOptions = {}
  ): Promise<any> =>
    requestWithAbort<any>(`/v1/geometry/owners`, {
      method: 'POST',
      body: JSON.stringify({ geometry }),
      ...options,
    }),

  getPointMatrikkelenhet: (
    lat: number,
    lon: number,
    options: RequestOptions = {}
  ): Promise<any> =>
    requestWithAbort<any>(`/v1/point/matrikkelenhet`, {
      method: 'POST',
      body: JSON.stringify({ lat, lon }),
      ...options,
    }),
};
