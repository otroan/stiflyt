/** Map view component with Leaflet and Geoman */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MapContainer, TileLayer, GeoJSON as ReactLeafletGeoJSON, useMap, LayersControl, LayerGroup } from 'react-leaflet';
import L from 'leaflet';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import type { Changeset, LocalEvent, RoutesResponse, RouteSegmentsResponse, RouteLinksResponse, RouteInfo, SegmentRoutesItem, SegmentAddEvent, SegmentDeleteNewEvent, SegmentRetireEvent, AnchorNodeInfo, PlacenameCandidate, AnchorNameUpsertRequest, FacilityCandidate, SignsReportResponse } from '../types';
import type { GeoJSON } from 'geojson';
import { SnapManager } from '../utils/snap';
import { api, isAbortError } from '../api/client';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';
import { findClosestPointOnLine, splitLineStringAtPoint, isNewSegment } from '../utils/geometry';
import { ConfirmDialog } from './ConfirmDialog';
import { AnchorNameDialog } from './AnchorNameDialog';
import { RouteSelectorPanel } from './RouteSelectorPanel';
import 'leaflet/dist/leaflet.css';

// Load Geoman dynamically to avoid Vite resolution issues
// Import is done in GeomanControl component when needed
const debugLog = (...args: unknown[]) => {
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.log(...args);
  }
};

// Fix Leaflet default icon issue
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';
const DefaultIcon = L.icon({
  iconUrl: icon,
  shadowUrl: iconShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

interface MapViewProps {
  changeset: Changeset | null;
  routeGeometry?: GeoJSON.Geometry | null;
  routeNumber?: string | null;
  selectedRouteNumber?: string | null;
  onRouteSelect?: (rutenummer: string | null) => void;
  onEventAdded: (event: LocalEvent) => void;
  selectedFeatureId?: string;
  selectedFeatureIds?: Set<string>; // Multi-select support - all selected feature IDs
  onFeatureSelect?: (id: string, properties?: Record<string, unknown>, isMultiSelect?: boolean) => void;
  onOpenEditForm?: () => void; // Callback to open edit form in InfoPanel
  localEventsCount?: number;
  signsPrefix?: string | null; // Prefix for loading signs by area
  signsData?: SignsReportResponse | null; // Lifted from App when provided
  onSignsDataLoad?: (data: SignsReportResponse | null) => void; // Callback when signs data is loaded
  onSignDestinationSelect?: (destKey: string, selected: boolean) => void; // Callback for destination selection
  selectedSignDestinations?: Set<string>; // Selected destination keys
  showLinks: boolean;
  onShowLinksChange: (v: boolean) => void;
  showSegments: boolean;
  onShowSegmentsChange: (v: boolean) => void;
  showAnchors: boolean;
  onShowAnchorsChange: (v: boolean) => void;
  showSigns: boolean;
  onShowSignsChange: (v: boolean) => void;
  showOwnership: boolean;
  onShowOwnershipChange: (v: boolean) => void;
  editMode: boolean;
  onEditModeChange: (v: boolean) => void;
  selectedGeometryForOwnership?: GeoJSON.Geometry | null;
  onGeometrySelectForOwnership?: (geometry: GeoJSON.Geometry | null) => void;
  ownershipData?: any;
  onOwnershipDataChange?: (data: any) => void;
  selectedArea?: string | null; // Area prefix (e.g., 'bre', 'jot')
}

// Component to render the segments layer for LayersControl
function SegmentsLayer({
  segmentsData,
  segmentsLayerRef,
  selectedFeatureId,
  selectedFeatureIds,
  onFeatureSelect,
  onSegmentHoverStart,
  onSegmentHoverMove,
  onSegmentHoverEnd,
}: {
  segmentsData: GeoJSON.FeatureCollection | null;
  segmentsLayerRef: React.MutableRefObject<L.GeoJSON | null>;
  selectedFeatureId?: string;
  selectedFeatureIds?: Set<string>;
  onFeatureSelect?: (id: string, properties?: Record<string, unknown>, isMultiSelect?: boolean) => void;
  onSegmentHoverStart?: (segmentId: string, layer: L.Layer, latlng: L.LatLng) => void;
  onSegmentHoverMove?: (segmentId: string, layer: L.Layer, latlng: L.LatLng) => void;
  onSegmentHoverEnd?: (segmentId: string, layer: L.Layer) => void;
}) {
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const map = useMap();

  // Initialize layer group and sync with segmentsLayerRef
  useEffect(() => {
    if (!layerGroupRef.current) {
      layerGroupRef.current = L.layerGroup();
    }
  }, []);

  // Update segments when data or selection changes
  useEffect(() => {
    if (!layerGroupRef.current || !segmentsData) {
      if (layerGroupRef.current) {
        layerGroupRef.current.clearLayers();
      }
      segmentsLayerRef.current = null;
      return;
    }

    // Clear previous layers
    layerGroupRef.current.clearLayers();

    const segmentsLayer = L.geoJSON(segmentsData, {
      style: (feature) => {
        const props = feature?.properties as { objid?: number | string; segment_objid?: number | string; [key: string]: unknown } | null;
        const featureId = feature?.id
          ? String(feature.id)
          : props?.objid
            ? String(props.objid)
            : props?.segment_objid
              ? String(props.segment_objid)
              : null;
        const isSelected = featureId && (selectedFeatureIds?.has(featureId) || (selectedFeatureId && String(featureId) === String(selectedFeatureId)));
        return {
          color: isSelected ? '#2196f3' : '#9b59b6',
          weight: isSelected ? 6 : 4,
          opacity: isSelected ? 1.0 : 0.8,
        };
      },
      onEachFeature: (feature, layer) => {
        const props = feature.properties as { objid?: number | string; rutenummer?: string; rutenavn?: string | null; length_m?: number | null; [key: string]: unknown } | null;
        const featureId = feature.id
          ? String(feature.id)
          : props?.objid
            ? String(props.objid)
            : props?.segment_objid
              ? String(props.segment_objid)
              : null;

        if (props) {
          layer.bindPopup(`
            <strong>Segment ${props.objid ?? 'N/A'}</strong><br>
            Rute: ${props.rutenummer || 'N/A'}<br>
            Navn: ${props.rutenavn || 'Uten navn'}<br>
            Lengde: ${typeof props.length_m === 'number' ? props.length_m.toFixed(2) : 'N/A'} m
          `);
        }

        layer.on('click', (e: L.LeafletMouseEvent) => {
          if (onFeatureSelect && featureId) {
            const featureProps = feature.properties as Record<string, unknown> | null;
            const isMultiSelect = e.originalEvent.ctrlKey || e.originalEvent.metaKey;
            onFeatureSelect(featureId, featureProps || undefined, isMultiSelect);
          }
        });

        if (featureId) {
          layer.on('mouseover', (e: L.LeafletMouseEvent) => {
            onSegmentHoverStart?.(featureId, layer, e.latlng);
          });
          layer.on('mousemove', (e: L.LeafletMouseEvent) => {
            onSegmentHoverMove?.(featureId, layer, e.latlng);
          });
          layer.on('mouseout', () => {
            onSegmentHoverEnd?.(featureId, layer);
          });
        }
      },
    });

    // Add to layer group (not directly to map - LayersControl handles that)
    layerGroupRef.current.addLayer(segmentsLayer);
    segmentsLayerRef.current = segmentsLayer;
  }, [segmentsData, selectedFeatureId, selectedFeatureIds, onFeatureSelect, segmentsLayerRef]);

  return <LayerGroup ref={layerGroupRef} />;
}

// Component to render the links layer for LayersControl
function LinksLayer({
  linksData,
  linksLayerRef,
  selectedFeatureId,
  selectedFeatureIds,
  onFeatureSelect,
  showOwnership,
  onGeometrySelectForOwnership,
  onOwnershipDataChange,
  selectedRouteNumber,
  onRouteSelect,
  onCacheInvalidateRef,
}: {
  linksData: GeoJSON.FeatureCollection | null;
  linksLayerRef: React.MutableRefObject<L.GeoJSON | null>;
  selectedFeatureId?: string;
  selectedFeatureIds?: Set<string>;
  onFeatureSelect?: (id: string, properties?: Record<string, unknown>, isMultiSelect?: boolean) => void;
  showOwnership?: boolean;
  onGeometrySelectForOwnership?: (geometry: GeoJSON.Geometry | null) => void;
  onOwnershipDataChange?: (data: any) => void;
  selectedRouteNumber?: string | null;
  onRouteSelect?: (rutenummer: string | null) => void;
  onCacheInvalidateRef?: React.MutableRefObject<(() => void) | null>;
}) {
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const map = useMap();

  // Cache for route links and route info
  const routeLinksCacheRef = useRef<Map<string, GeoJSON.Feature[]>>(new Map());
  const routeInfoCacheRef = useRef<Map<string, { rutenummer: string; rutenavn: string | null; total_length_m: number; from_name: string | null; to_name: string | null }>>(new Map());

  // Expose cache invalidation function to parent
  useEffect(() => {
    if (onCacheInvalidateRef) {
      onCacheInvalidateRef.current = () => {
        routeInfoCacheRef.current.clear();
      };
    }
    return () => {
      if (onCacheInvalidateRef) {
        onCacheInvalidateRef.current = null;
      }
    };
  }, [onCacheInvalidateRef]);
  const highlightedRouteRef = useRef<string | null>(null);
  const originalStylesRef = useRef<Map<string, L.PathOptions>>(new Map());
  const linkLayersRef = useRef<Map<string, L.Path>>(new Map());
  const pendingBulkFetchRef = useRef<Promise<void> | null>(null);
  const mouseoutTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // State for route selector panel
  const [routeSelectorVisible, setRouteSelectorVisible] = useState(false);
  const [routeSelectorRoutes, setRouteSelectorRoutes] = useState<Array<{ rutenummer: string; rutenavn: string | null; totalKm?: number }>>([]);
  const [routeSelectorPosition, setRouteSelectorPosition] = useState({ x: 0, y: 0 });
  const [routeSelectorCurrentIndex, setRouteSelectorCurrentIndex] = useState(0);

  // Initialize layer group
  useEffect(() => {
    if (!layerGroupRef.current) {
      layerGroupRef.current = L.layerGroup();
    }
  }, []);

  // Pre-fetch route info for all unique routes in links (bulk fetch)
  useEffect(() => {
    if (!linksData || !linksData.features || linksData.features.length === 0) {
      return;
    }

    // Collect all unique route numbers from links
    const uniqueRouteNumbers = new Set<string>();
    linksData.features.forEach((feature) => {
      const props = feature.properties as {
        routes?: { rutenummer?: string }[];
        [key: string]: unknown;
      } | null;
      if (props?.routes) {
        props.routes.forEach((r) => {
          if (r.rutenummer) {
            uniqueRouteNumbers.add(r.rutenummer);
          }
        });
      }
    });

    // Check which routes are missing from cache
    const missingRoutes = Array.from(uniqueRouteNumbers).filter(
      (rn) => !routeInfoCacheRef.current.has(rn)
    );

    // Bulk fetch missing routes (max 100 at a time)
    if (missingRoutes.length > 0 && missingRoutes.length <= 100) {
      // Prevent multiple simultaneous bulk fetches
      if (!pendingBulkFetchRef.current) {
        pendingBulkFetchRef.current = api
          .getRoutesBulk(missingRoutes, false)
          .then((bulkResponse) => {
            // Cache all route info
            bulkResponse.routes.forEach((route) => {
              const cachedInfo = {
                rutenummer: route.rutenummer,
                rutenavn: route.rutenavn || null,
                total_length_m: (route as any).total_length_m || (route as any).total_length_meters || 0,
                from_name: (route as any).from_name || null,
                to_name: (route as any).to_name || null,
              };
              routeInfoCacheRef.current.set(route.rutenummer, cachedInfo);
              // Debug: Log endpoint names for troubleshooting
              if (cachedInfo.from_name || cachedInfo.to_name) {
                console.log(`Cached endpoints for ${route.rutenummer}:`, {
                  from_name: cachedInfo.from_name,
                  to_name: cachedInfo.to_name,
                });
              }
            });
            pendingBulkFetchRef.current = null;
          })
          .catch((error) => {
            if (!isAbortError(error)) {
              debugLog('Bulk route fetch failed (optional):', error);
            }
            pendingBulkFetchRef.current = null;
          });
      }
    }
  }, [linksData]);

  // Function to clear route highlight
  const clearRouteHighlight = useCallback(() => {
    if (!highlightedRouteRef.current) return;

    // Restore original styles
    linkLayersRef.current.forEach((layer, layerId) => {
      const originalStyle = originalStylesRef.current.get(layerId);
      if (originalStyle) {
        layer.setStyle(originalStyle);
      }
    });

    linkLayersRef.current.clear();
    originalStylesRef.current.clear();
    highlightedRouteRef.current = null;
  }, []);

  // Function to highlight all links for a route
  const highlightRouteLinks = useCallback(async (rutenummer: string) => {
    console.log('highlightRouteLinks called for:', rutenummer);

    if (highlightedRouteRef.current === rutenummer) {
      console.log('Already highlighted, skipping');
      return; // Already highlighted
    }

    // Clear previous highlight
    if (highlightedRouteRef.current) {
      clearRouteHighlight();
    }

    highlightedRouteRef.current = rutenummer;

    // Highlight all VISIBLE links on the map that belong to this route
    if (linksLayerRef.current) {
      let highlightedCount = 0;
      linksLayerRef.current.eachLayer((layer) => {
        if (layer instanceof L.Path) {
          const feature = (layer as any).feature as GeoJSON.Feature | undefined;
          if (feature) {
            const props = feature.properties as {
              routes?: { rutenummer?: string }[];
              [key: string]: unknown;
            } | null;

            // Check if this link belongs to the selected route
            const belongsToRoute = props?.routes?.some(
              (r) => r.rutenummer === rutenummer
            );

            if (belongsToRoute) {
              highlightedCount++;
              const featureId = feature.id ? String(feature.id) : String((feature.properties as any)?.link_id || '');

              // Get current style to preserve color
              const currentOptions = layer.options as L.PathOptions;
              const originalColor = currentOptions.color || '#16a085';
              const originalWeight = currentOptions.weight || 4;
              const originalOpacity = currentOptions.opacity || 0.85;

              // Save original style if not already saved
              const layerId = featureId;
              if (!originalStylesRef.current.has(layerId)) {
                originalStylesRef.current.set(layerId, {
                  color: originalColor,
                  weight: originalWeight,
                  opacity: originalOpacity,
                  dashArray: currentOptions.dashArray || '5, 5',
                });
              }

              // Apply highlight style - same color as route, but thicker and dashed
              layer.setStyle({
                color: originalColor, // Same color as underlying route
                weight: originalWeight + 2, // Slightly thicker (add 2 to original weight)
                opacity: Math.min(originalOpacity + 0.1, 1.0), // Slightly more opaque
                dashArray: '10, 5', // Dashed pattern
              });
              layer.bringToFront();

              linkLayersRef.current.set(layerId, layer);
            }
          }
        }
      });
      console.log(`Highlighted ${highlightedCount} links for route ${rutenummer}`);
    } else {
      console.log('linksLayerRef.current is null');
    }
  }, [clearRouteHighlight]);

  // Update links when data or selection changes
  useEffect(() => {
    if (!layerGroupRef.current || !linksData) {
      if (layerGroupRef.current) {
        layerGroupRef.current.clearLayers();
      }
      linksLayerRef.current = null;
      return;
    }

    // Clear previous layers
    layerGroupRef.current.clearLayers();

    const linksLayer = L.geoJSON(linksData, {
      style: (feature) => {
        const props = feature?.properties as {
          link_id?: number;
          routes?: { rutenummer?: string; [key: string]: unknown }[];
          [key: string]: unknown;
        } | null;
        const featureId = feature?.id
          ? String(feature.id)
          : props?.link_id
            ? String(props.link_id)
            : null;
        const isSelected =
          featureId &&
          (selectedFeatureIds?.has(featureId) ||
            (selectedFeatureId && String(featureId) === String(selectedFeatureId)));

        // Note: Route highlighting is handled dynamically in highlightRouteLinks
        // This style function is for initial rendering only

        return {
          color: isSelected ? '#2196f3' : '#16a085',
          weight: isSelected ? 5 : 4,
          opacity: isSelected ? 1.0 : 0.85,
          dashArray: '5, 5',
        };
      },
      onEachFeature: (feature, layer) => {
        // Store feature reference on layer for later use
        (layer as any).feature = feature;

        const props = feature.properties as {
          link_id?: number;
          a_node?: number | null;
          b_node?: number | null;
          length_m?: number | null;
          routes?: { rutenummer?: string; rutenavn?: string | null; vedlikeholdsansvarlig?: string | null }[];
          [key: string]: unknown;
        } | null;
        const featureId = feature.id
          ? String(feature.id)
          : props?.link_id
            ? String(props.link_id)
            : null;
        const routes = props?.routes || [];

        // Debug: Log routes for this link
        if (routes.length > 0) {
          const routeNumbers = routes.map(r => r.rutenummer || 'N/A').join(', ');
          console.log(`Link ${props?.link_id || featureId || 'N/A'} belongs to routes: [${routeNumbers}] (total: ${routes.length})`);
        } else {
          console.log(`Link ${props?.link_id || featureId || 'N/A'} has NO routes`);
        }

        if (props) {
          const lengthStr =
            typeof props.length_m === 'number' ? `${props.length_m.toFixed(1)} m` : 'N/A';

          // Create initial tooltip content
          let routesHtml = '';

          if (routes.length === 0) {
            routesHtml = '<div style="opacity:0.8;">Ingen ruter registrert</div>';
          } else if (routes.length === 1) {
            // Single route - show basic info with endpoints, will be updated with total km on hover
            const r = routes[0];
            const rn = r.rutenummer || 'Ukjent rute';
            const routeInfo = routeInfoCacheRef.current.get(rn);
            // Show endpoints if available, otherwise fallback to route name
            const fromName = routeInfo?.from_name || null;
            const toName = routeInfo?.to_name || null;
            let endpointDisplay = '';
            if (fromName && toName) {
              endpointDisplay = `${fromName} → ${toName}`;
            } else if (fromName || toName) {
              endpointDisplay = fromName || toName || '';
            } else {
              // Fallback to route name if endpoints not available
              endpointDisplay = r.rutenavn || 'Uten navn';
            }
            routesHtml = `
              <div style="margin-top:4px;">
                <div><strong>${rn}</strong></div>
                <div style="opacity:0.9;">${endpointDisplay}</div>
              </div>
            `;
          } else {
            // Multiple routes - make clickable
            // Build routes HTML - bulk fetch happens in separate useEffect
            routesHtml = routes
              .map((r) => {
                const rn = r.rutenummer || 'Ukjent rute';
                const routeInfo = routeInfoCacheRef.current.get(rn);
                const totalKm = routeInfo?.total_length_m
                  ? `${(routeInfo.total_length_m / 1000).toFixed(1)} km`
                  : '';
                // Show endpoints if available, otherwise fallback to route name
                const fromName = routeInfo?.from_name || null;
                const toName = routeInfo?.to_name || null;
                let endpointDisplay = '';
                if (fromName && toName) {
                  endpointDisplay = `${fromName} → ${toName}`;
                } else if (fromName || toName) {
                  endpointDisplay = fromName || toName || '';
                } else {
                  // Fallback to route name if endpoints not available
                  endpointDisplay = r.rutenavn || 'Uten navn';
                }
                return `
                  <div
                    class="route-tooltip-item"
                    data-rutenummer="${rn}"
                    style="
                      margin-top:4px;
                      padding:4px 8px;
                      cursor:pointer;
                      border-radius:4px;
                      background:#f5f5f5;
                      border:1px solid #ddd;
                    "
                    onmouseover="this.style.background='#e0e0e0'"
                    onmouseout="this.style.background='#f5f5f5'"
                  >
                    <div><strong>${rn}</strong></div>
                    <div style="opacity:0.9;">${endpointDisplay}</div>
                    ${totalKm ? `<div style="opacity:0.85; font-size:11px;">${totalKm}</div>` : ''}
                  </div>
                `;
              })
              .join('');

            // Update tooltip when bulk fetch completes (if routes were missing)
            const missingRoutes = routes.map((r) => r.rutenummer).filter((rn): rn is string => !!rn && !routeInfoCacheRef.current.has(rn));
            if (missingRoutes.length > 0) {
              // Wait for bulk fetch to complete, then update tooltip
              const updateTooltipWhenReady = () => {
                const allCached = routes.every((r) => {
                  const rn = r.rutenummer;
                  return !rn || routeInfoCacheRef.current.has(rn);
                });

                if (allCached) {
                  // All routes are now cached, update tooltip
                  const updatedRoutesHtml = routes
                    .map((r) => {
                      const rn = r.rutenummer || 'Ukjent rute';
                      const routeInfo = routeInfoCacheRef.current.get(rn);
                      const totalKm = routeInfo?.total_length_m
                        ? `${(routeInfo.total_length_m / 1000).toFixed(1)} km`
                        : '';
                      // Show endpoints if available, otherwise fallback to route name
                      const fromName = routeInfo?.from_name || null;
                      const toName = routeInfo?.to_name || null;
                      let endpointDisplay = '';
                      if (fromName && toName) {
                        endpointDisplay = `${fromName} → ${toName}`;
                      } else if (fromName || toName) {
                        endpointDisplay = fromName || toName || '';
                      } else {
                        // Fallback to route name if endpoints not available
                        endpointDisplay = r.rutenavn || 'Uten navn';
                      }
                      return `
                        <div
                          class="route-tooltip-item"
                          data-rutenummer="${rn}"
                          style="
                            margin-top:4px;
                            padding:4px 8px;
                            cursor:pointer;
                            border-radius:4px;
                            background:#f5f5f5;
                            border:1px solid #ddd;
                          "
                          onmouseover="this.style.background='#e0e0e0'"
                          onmouseout="this.style.background='#f5f5f5'"
                        >
                          <div><strong>${rn}</strong></div>
                          <div style="opacity:0.9;">${endpointDisplay}</div>
                          ${totalKm ? `<div style="opacity:0.85; font-size:11px;">${totalKm}</div>` : ''}
                        </div>
                      `;
                    })
                    .join('');

                  const updatedContent = `
                    <div style="font-size:12px; line-height:1.35;">
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <div style="opacity:0.8;">Velg rute:</div>
                        <button
                          class="tooltip-close-btn"
                          style="
                            background:none;
                            border:none;
                            color:#666;
                            cursor:pointer;
                            font-size:16px;
                            line-height:1;
                            padding:0;
                            margin-left:8px;
                            opacity:0.7;
                          "
                          onmouseover="this.style.opacity='1'"
                          onmouseout="this.style.opacity='0.7'"
                          title="Lukk"
                        >×</button>
                      </div>
                      ${updatedRoutesHtml}
                    </div>
                  `;

                  layer.setTooltipContent(updatedContent);
                  // Ensure tooltip is still interactive - update className via DOM
                  const tooltip = layer.getTooltip();
                  if (tooltip) {
                    const tooltipEl = tooltip.getElement();
                    if (tooltipEl) {
                      tooltipEl.className = 'leaflet-tooltip route-tooltip-interactive';
                    }
                  }
                  // Re-attach click handlers after content update
                  setTimeout(() => {
                    const tooltipEl = tooltip?.getElement();
                    if (tooltipEl) {
                      const handleClick = async (e: MouseEvent) => {
                        e.stopPropagation();
                        e.preventDefault();
                        const target = e.target as HTMLElement;

                        // Check if close button was clicked
                        const closeBtn = target.closest('.tooltip-close-btn');
                        if (closeBtn) {
                          const tooltip = layer.getTooltip();
                          if (tooltip) {
                            tooltip.close();
                            clearRouteHighlight();
                          }
                          return;
                        }

                        const routeItem = target.closest('.route-tooltip-item') as HTMLElement;
                        if (routeItem) {
                          const rutenummer = routeItem.getAttribute('data-rutenummer');
                          if (rutenummer) {
                            await highlightRouteLinks(rutenummer);
                            const route = routes.find((r) => r.rutenummer === rutenummer);
                            if (route) {
                              const routeInfo = routeInfoCacheRef.current.get(rutenummer);
                              const totalKm = routeInfo?.total_length_m
                                ? `${(routeInfo.total_length_m / 1000).toFixed(1)} km`
                                : '';
                              // Show endpoints if available, otherwise fallback to route name
                              const fromName = routeInfo?.from_name || null;
                              const toName = routeInfo?.to_name || null;
                              let endpointDisplay = '';
                              if (fromName && toName) {
                                endpointDisplay = `${fromName} → ${toName}`;
                              } else if (fromName || toName) {
                                endpointDisplay = fromName || toName || '';
                              } else {
                                // Fallback to route name if endpoints not available
                                endpointDisplay = route.rutenavn || 'Uten navn';
                              }
                              const selectedContent = `
                                <div style="font-size:12px; line-height:1.35;">
                                  <div><strong>${rutenummer}</strong></div>
                                  <div style="opacity:0.9;">${endpointDisplay}</div>
                                  ${totalKm ? `<div style="opacity:0.85;">${totalKm}</div>` : ''}
                                </div>
                              `;
                              layer.setTooltipContent(selectedContent);
                              const updatedTooltip = layer.getTooltip();
                              if (updatedTooltip) {
                                const tooltipEl = updatedTooltip.getElement();
                                if (tooltipEl) {
                                  tooltipEl.className = 'leaflet-tooltip route-tooltip';
                                }
                                // Make tooltip non-permanent after selection
                                updatedTooltip.options.permanent = false;
                              }
                            }
                          }
                        }
                      };
                      tooltipEl.removeEventListener('mousedown', handleClick);
                      tooltipEl.addEventListener('mousedown', handleClick, true);
                    }
                  }, 50);
                } else {
                  // Check again after a short delay
                  setTimeout(updateTooltipWhenReady, 100);
                }
              };

              // Start checking after a short delay to allow bulk fetch to start
              setTimeout(updateTooltipWhenReady, 200);
            }
          }

          // Build initial tooltip content - show route info, not link info
          let initialTooltipContent = '';
          if (routes.length === 0) {
            initialTooltipContent = `
              <div style="font-size:12px; line-height:1.35;">
                <div style="opacity:0.8;">Ingen ruter registrert</div>
              </div>
            `;
          } else if (routes.length === 1) {
            // Single route - show route info with endpoints
            const r = routes[0];
            const rn = r.rutenummer || 'Ukjent rute';
            const routeInfo = routeInfoCacheRef.current.get(rn);
            const totalKm = routeInfo?.total_length_m
              ? `${(routeInfo.total_length_m / 1000).toFixed(1)} km`
              : '';
            // Show endpoints if available, otherwise fallback to route name
            const fromName = routeInfo?.from_name || null;
            const toName = routeInfo?.to_name || null;
            // Debug: Log what we're using for tooltip
            if (routeInfo) {
              console.log(`Tooltip for route ${rn}:`, {
                from_name: fromName,
                to_name: toName,
                has_from: !!fromName,
                has_to: !!toName,
                cached: true,
              });
            } else {
              console.log(`Tooltip for route ${rn}:`, {
                cached: false,
                will_fallback_to: r.rutenavn || 'Uten navn',
              });
            }
            let endpointDisplay = '';
            if (fromName && toName) {
              endpointDisplay = `<div style="opacity:0.9;">${fromName} → ${toName}</div>`;
            } else if (fromName || toName) {
              endpointDisplay = `<div style="opacity:0.9;">${fromName || toName}</div>`;
            } else {
              // Fallback to route name if endpoints not available
              const navn = r.rutenavn || 'Uten navn';
              endpointDisplay = `<div style="opacity:0.9;">${navn}</div>`;
            }
            initialTooltipContent = `
              <div style="font-size:12px; line-height:1.35;">
                <div><strong>${rn}</strong></div>
                ${endpointDisplay}
                ${totalKm ? `<div style="opacity:0.85;">${totalKm}</div>` : ''}
              </div>
            `;

            // If route info is not cached yet, update tooltip when cache is ready
            if (!routeInfo || (!routeInfo.from_name && !routeInfo.to_name)) {
              const missingRoutes = [rn].filter((rn): rn is string => !!rn && !routeInfoCacheRef.current.has(rn));
              if (missingRoutes.length > 0) {
                // Wait for bulk fetch to complete, then update tooltip
                const updateTooltipWhenReady = () => {
                  const cachedRouteInfo = routeInfoCacheRef.current.get(rn);
                  if (cachedRouteInfo && (cachedRouteInfo.from_name || cachedRouteInfo.to_name)) {
                    // Cache is ready with endpoint names, update tooltip
                    const cachedTotalKm = cachedRouteInfo.total_length_m
                      ? `${(cachedRouteInfo.total_length_m / 1000).toFixed(1)} km`
                      : '';
                    const cachedFromName = cachedRouteInfo.from_name || null;
                    const cachedToName = cachedRouteInfo.to_name || null;
                    let cachedEndpointDisplay = '';
                    if (cachedFromName && cachedToName) {
                      cachedEndpointDisplay = `<div style="opacity:0.9;">${cachedFromName} → ${cachedToName}</div>`;
                    } else if (cachedFromName || cachedToName) {
                      cachedEndpointDisplay = `<div style="opacity:0.9;">${cachedFromName || cachedToName}</div>`;
                    } else {
                      cachedEndpointDisplay = `<div style="opacity:0.9;">${r.rutenavn || 'Uten navn'}</div>`;
                    }
                    const updatedContent = `
                      <div style="font-size:12px; line-height:1.35;">
                        <div><strong>${rn}</strong></div>
                        ${cachedEndpointDisplay}
                        ${cachedTotalKm ? `<div style="opacity:0.85;">${cachedTotalKm}</div>` : ''}
                      </div>
                    `;
                    layer.setTooltipContent(updatedContent);
                  } else if (routeInfoCacheRef.current.has(rn)) {
                    // Cache is ready but no endpoints, stop checking
                    return;
                  } else {
                    // Cache not ready yet, check again
                    setTimeout(updateTooltipWhenReady, 100);
                  }
                };
                // Start checking after a short delay to allow bulk fetch to start
                setTimeout(updateTooltipWhenReady, 200);
              }
            }
          } else {
            // Multiple routes - show simple tooltip, panel will be shown on hover
            initialTooltipContent = `
              <div style="font-size:12px; line-height:1.35;">
                <div style="opacity:0.8;">${routes.length} ruter - velg fra panel</div>
              </div>
            `;
          }

          // Bind tooltip with different className for interactive tooltips
          const tooltipClassName = routes.length > 1 ? 'route-tooltip-interactive' : 'route-tooltip';
          console.log(`Binding tooltip for link ${props.link_id || featureId || 'N/A'}:`, {
            routesCount: routes.length,
            routeNumbers: routes.map(r => r.rutenummer || 'N/A'),
            tooltipClassName,
            interactive: routes.length > 1,
            contentPreview: initialTooltipContent.substring(0, 150)
          });

          // Bind tooltip - simple tooltip for all routes
          layer.bindTooltip(initialTooltipContent, {
            permanent: false,
            direction: 'top',
            offset: [0, -8],
            className: tooltipClassName,
            sticky: true,
            interactive: false, // Panel handles interaction, not tooltip
          });

          // For multiple routes, panel is shown on mouseover (handled below)
          // No need for complex tooltip click handlers
        }

        // Mouseover handler - highlight route and show route selector panel
        let hoverTimeout: ReturnType<typeof setTimeout> | null = null;

        layer.on('mouseover', async (e: L.LeafletMouseEvent) => {
          console.log(`Mouseover on link ${props?.link_id || featureId || 'N/A'}, routes:`, routes.map(r => r.rutenummer || 'N/A'));

          // Clear any pending mouseout timeout
          if (mouseoutTimeoutRef.current) {
            clearTimeout(mouseoutTimeoutRef.current);
            mouseoutTimeoutRef.current = null;
          }

          // Clear any pending timeout
          if (hoverTimeout) {
            clearTimeout(hoverTimeout);
            hoverTimeout = null;
          }

          // Small delay to prevent flickering
          hoverTimeout = setTimeout(async () => {
            if (routes.length === 1 && routes[0]?.rutenummer) {
              // Single route - highlight immediately and update tooltip with total km
              const rutenummer = routes[0].rutenummer;
              console.log(`Highlighting single route ${rutenummer} on mouseover`);
              await highlightRouteLinks(rutenummer);

              // Load route info for tooltip (should already be cached from bulk fetch)
              const routeInfo = routeInfoCacheRef.current.get(rutenummer);
              if (routeInfo) {
                // Update tooltip with total km
                const totalKm = routeInfo.total_length_m
                  ? `${(routeInfo.total_length_m / 1000).toFixed(1)} km`
                  : '';
                // Show endpoints if available, otherwise fallback to route name
                const fromName = routeInfo.from_name || null;
                const toName = routeInfo.to_name || null;
                let endpointDisplay = '';
                if (fromName && toName) {
                  endpointDisplay = `${fromName} → ${toName}`;
                } else if (fromName || toName) {
                  endpointDisplay = fromName || toName || '';
                } else {
                  // Fallback to route name if endpoints not available
                  endpointDisplay = routeInfo.rutenavn || 'Uten navn';
                }

                const updatedContent = `
                  <div style="font-size:12px; line-height:1.35;">
                    <div><strong>${rutenummer}</strong></div>
                    <div style="opacity:0.9;">${endpointDisplay}</div>
                    ${totalKm ? `<div style="opacity:0.85;">${totalKm}</div>` : ''}
                  </div>
                `;

                console.log(`Updating tooltip content for single route:`, updatedContent.substring(0, 100));
                layer.setTooltipContent(updatedContent);
              }
            } else if (routes.length > 1) {
              // Multiple routes - show route selector panel
              console.log(`Multiple routes detected (${routes.length}), showing route selector panel`);

              // Convert routes to panel format with total km and endpoints
              const panelRoutes = routes.map(r => {
                const rn = r.rutenummer || '';
                const routeInfo = routeInfoCacheRef.current.get(rn);
                // Use endpoints if available, otherwise fallback to route name
                const fromName = routeInfo?.from_name || null;
                const toName = routeInfo?.to_name || null;
                let endpointDisplay = '';
                if (fromName && toName) {
                  endpointDisplay = `${fromName} → ${toName}`;
                } else if (fromName || toName) {
                  endpointDisplay = fromName || toName || '';
                } else {
                  endpointDisplay = r.rutenavn || 'Uten navn';
                }
                return {
                  rutenummer: rn,
                  rutenavn: endpointDisplay, // Use endpoints instead of route name
                  totalKm: routeInfo?.total_length_m ? routeInfo.total_length_m / 1000 : undefined,
                };
              });

              // Get mouse position in container coordinates
              const containerPoint = map.latLngToContainerPoint(e.latlng);
              const container = map.getContainer();
              const containerRect = container.getBoundingClientRect();

              // Calculate position relative to viewport (for fixed positioning)
              setRouteSelectorRoutes(panelRoutes);
              setRouteSelectorPosition({
                x: containerRect.left + containerPoint.x,
                y: containerRect.top + containerPoint.y - 20
              });
              setRouteSelectorCurrentIndex(0);
              setRouteSelectorVisible(true);
            }
          }, 100);
        });

        // Mouseout handler - close panel after delay (if not hovering over panel)
        layer.on('mouseout', () => {
          if (hoverTimeout) {
            clearTimeout(hoverTimeout);
            hoverTimeout = null;
          }

          if (routes.length > 1) {
            // For multiple routes, close panel after delay (allows moving mouse to panel)
            // Clear any existing timeout
            if (mouseoutTimeoutRef.current) {
              clearTimeout(mouseoutTimeoutRef.current);
            }

            mouseoutTimeoutRef.current = setTimeout(() => {
              // Check if mouse is over panel before closing
              const panelElement = document.querySelector('.route-selector-panel');
              if (panelElement && (panelElement.matches(':hover') || panelElement.querySelector(':hover'))) {
                // Mouse is over panel, don't close - check again later
                mouseoutTimeoutRef.current = setTimeout(() => {
                  const stillOverPanel = document.querySelector('.route-selector-panel');
                  if (!stillOverPanel || (!stillOverPanel.matches(':hover') && !stillOverPanel.querySelector(':hover'))) {
                    setRouteSelectorVisible(false);
                    clearRouteHighlight();
                  }
                  mouseoutTimeoutRef.current = null;
                }, 200);
                return;
              }
              // Mouse is not over panel, close it
              setRouteSelectorVisible(false);
              clearRouteHighlight();
              mouseoutTimeoutRef.current = null;
            }, 300); // Delay to allow moving mouse to panel
            return;
          }

          // For single route, clear highlight after delay (allows moving to tooltip)
          setTimeout(() => {
            // Only clear if mouse is not over tooltip
            const tooltip = layer.getTooltip();
            if (!tooltip || !tooltip.getElement()?.matches(':hover')) {
              clearRouteHighlight();
            }
          }, 200);
        });

        layer.on('click', (e: L.LeafletMouseEvent) => {
          // Property ownership mode: fetch ownership for link geometry
          if (showOwnership && onGeometrySelectForOwnership && feature.geometry) {
            if (feature.geometry.type === 'LineString') {
              onGeometrySelectForOwnership(feature.geometry);
              // Fetch ownership data
              if (onOwnershipDataChange) {
                onOwnershipDataChange(null);
                api.getGeometryOwners(feature.geometry)
                  .then((data) => {
                    if (onOwnershipDataChange) {
                      onOwnershipDataChange(data);
                    }
                  })
                  .catch((error) => {
                    const appError = handleApiError(error, 'Property Ownership');
                    notificationManager.error(`Kunne ikke laste grunneierinformasjon: ${appError.message}`);
                  });
              }
            }
            return;
          }

          // Route selection via link click (pick first route if any)
          if (onRouteSelect && routes.length > 0) {
            const route = routes[0];
            if (route?.rutenummer) {
              onRouteSelect(route.rutenummer);
            }
          }

          if (onFeatureSelect && featureId) {
            const featureProps = feature.properties as Record<string, unknown> | null;
            const isMultiSelect = e.originalEvent.ctrlKey || e.originalEvent.metaKey;
            onFeatureSelect(featureId, featureProps || undefined, isMultiSelect);
          }
        });
      },
    });

    // Add to layer group (not directly to map - LayersControl handles that)
    layerGroupRef.current.addLayer(linksLayer);
    linksLayerRef.current = linksLayer;

    // Cleanup on unmount or data change
    return () => {
      clearRouteHighlight();
      setRouteSelectorVisible(false);
      // Clear any pending timeouts
      if (mouseoutTimeoutRef.current) {
        clearTimeout(mouseoutTimeoutRef.current);
        mouseoutTimeoutRef.current = null;
      }
    };
  }, [linksData, selectedFeatureId, selectedFeatureIds, onFeatureSelect, linksLayerRef, showOwnership, onGeometrySelectForOwnership, onOwnershipDataChange, clearRouteHighlight, highlightRouteLinks, map]);

  // Handler for route selection from panel
  const handleRouteSelect = useCallback(async (rutenummer: string) => {
    await highlightRouteLinks(rutenummer);
    // Close panel after selection
    setRouteSelectorVisible(false);
  }, [highlightRouteLinks]);

  // Handler for closing panel
  const handleClosePanel = useCallback(() => {
    setRouteSelectorVisible(false);
    clearRouteHighlight();
  }, [clearRouteHighlight]);

  // Handler for navigation
  const handleNavigate = useCallback((direction: 'prev' | 'next') => {
    setRouteSelectorCurrentIndex((current) => {
      if (direction === 'prev') {
        return Math.max(0, current - 1);
      } else {
        return Math.min(routeSelectorRoutes.length - 1, current + 1);
      }
    });
  }, [routeSelectorRoutes.length]);

  // Close panel when clicking on map (outside panel)
  useEffect(() => {
    if (!routeSelectorVisible) return;

    const handleMapClick = (e: L.LeafletMouseEvent) => {
      // Check if click is inside panel
      const panelElement = document.querySelector('.route-selector-panel');
      if (panelElement && panelElement.contains(e.originalEvent.target as Node)) {
        return; // Click is inside panel, don't close
      }
      // Click is outside panel, close it
      setRouteSelectorVisible(false);
      clearRouteHighlight();
    };

    map.on('click', handleMapClick);
    return () => {
      map.off('click', handleMapClick);
    };
  }, [map, routeSelectorVisible, clearRouteHighlight]);

  // Get map container for portal
  const mapContainer = map.getContainer();

  return (
    <>
      <LayerGroup ref={layerGroupRef} />
      {routeSelectorVisible && routeSelectorRoutes.length > 0 && mapContainer && createPortal(
        <RouteSelectorPanel
          routes={routeSelectorRoutes}
          position={routeSelectorPosition}
          onRouteSelect={handleRouteSelect}
          onClose={handleClosePanel}
          currentIndex={routeSelectorCurrentIndex}
          onNavigate={handleNavigate}
        />,
        mapContainer
      )}
    </>
  );
}

// Component to render the signs layer for LayersControl
function SignsLayer({
  showSigns,
  signsData,
  selectedSignDestinations,
  onSignDestinationSelect,
  signsLayerRef
}: {
  showSigns: boolean;
  signsData: SignsReportResponse | null;
  selectedSignDestinations: Set<string>;
  onSignDestinationSelect?: (destKey: string, selected: boolean) => void;
  signsLayerRef: React.MutableRefObject<L.LayerGroup | null>;
}) {
  const map = useMap();
  const layerGroupRef = useRef<L.LayerGroup | null>(null);

  // Create our own layer and add/remove from map when overlay is on/off
  useEffect(() => {
    if (!showSigns) {
      if (layerGroupRef.current && map) {
        map.removeLayer(layerGroupRef.current);
        layerGroupRef.current = null;
        signsLayerRef.current = null;
      }
      return;
    }
    const lg = L.layerGroup();
    layerGroupRef.current = lg;
    signsLayerRef.current = lg;
    map.addLayer(lg);
    return () => {
      if (layerGroupRef.current) {
        map.removeLayer(layerGroupRef.current);
        layerGroupRef.current = null;
        signsLayerRef.current = null;
      }
    };
  }, [map, showSigns, signsLayerRef]);

  // Create markers when signs data changes (layer must exist and be on map)
  useEffect(() => {
    const group = layerGroupRef.current;
    if (!group || !signsData || !showSigns) {
      return;
    }

    group.clearLayers();

    // Create flag icon for endpoints (blue)
    const endpointFlagIcon = L.divIcon({
      className: 'sign-marker',
      html: '<div style="font-size: 20px; line-height: 1;">🚩</div>',
      iconSize: [20, 20],
      iconAnchor: [10, 20],
    });

    // Create flag icon for junctions (orange/red)
    const junctionFlagIcon = L.divIcon({
      className: 'sign-marker',
      html: '<div style="font-size: 20px; line-height: 1; filter: hue-rotate(20deg) saturate(1.5);">🚩</div>',
      iconSize: [20, 20],
      iconAnchor: [10, 20],
    });

    const formatDistanceKm = (distanceMeters?: number | null) => {
      if (distanceMeters === undefined || distanceMeters === null) return '';
      const km = distanceMeters / 1000;
      if (km > 5) {
        return `${Math.round(km)}km`;
      }
      return `${(Math.round(km * 2) / 2).toFixed(1)}km`;
    };

    signsData.signs.forEach((sign) => {
      const [lon, lat] = sign.coordinates || [null, null];
      if (lon === null || lat === null) return;

      const icon = sign.is_endpoint ? endpointFlagIcon : junctionFlagIcon;
      const marker = L.marker([lat, lon], { icon });
      group.addLayer(marker);

      // Create popup content with destinations
      const createDestinationPopup = (sign: typeof signsData.signs[0]) => {
        const signName = sign.name || `Anchor ${sign.anchor_node_id}`;
        const signType = sign.is_endpoint ? 'Endepunkt' : sign.is_junction ? 'Kryss' : 'Node';

        const destinationsHtml = sign.destinations.length > 0
          ? sign.destinations
              .map((dest) => {
                const destKey = `${sign.anchor_node_id}-${dest.anchor_node_id}`;
                const isSelected = selectedSignDestinations.has(destKey);
                return `
                  <div
                    class="sign-destination-item ${isSelected ? 'selected' : ''}"
                    data-dest-key="${destKey}"
                    style="
                      padding: 4px 8px;
                      margin: 2px 0;
                      cursor: pointer;
                      border-radius: 4px;
                      background: ${isSelected ? '#e3f2fd' : '#f5f5f5'};
                      border: 1px solid ${isSelected ? '#2196f3' : '#ddd'};
                    "
                    onmouseover="this.style.background='${isSelected ? '#bbdefb' : '#e0e0e0'}'"
                    onmouseout="this.style.background='${isSelected ? '#e3f2fd' : '#f5f5f5'}'"
                  >
                    ${isSelected ? '✓ ' : ''}${dest.name} (${formatDistanceKm(dest.distance_meters)})
                  </div>
                `;
              })
              .join('')
          : '<div style="padding: 4px; color: #999;">Ingen destinasjoner</div>';

        return `
          <div style="min-width: 200px;">
            <strong>${signName}</strong><br>
            <small>${signType} (${sign.anchor_node_id})</small><br>
            <br>
            <strong>Destinasjoner:</strong><br>
            ${destinationsHtml}
          </div>
        `;
      };

      marker.bindPopup(createDestinationPopup(sign), {
        maxWidth: 250,
      });

      // Handle click on destination items in popup
      marker.on('popupopen', () => {
        const popup = marker.getPopup();
        if (!popup) return;

        const popupElement = popup.getElement();
        if (!popupElement) return;

        // Add click handlers to destination items
        const destItems = popupElement.querySelectorAll('.sign-destination-item');
        destItems.forEach((item) => {
          const destKey = item.getAttribute('data-dest-key');
          if (!destKey) return;

          item.addEventListener('click', (e) => {
            e.stopPropagation();
            const isCurrentlySelected = selectedSignDestinations.has(destKey);
            if (onSignDestinationSelect) {
              onSignDestinationSelect(destKey, !isCurrentlySelected);
            }
            // Refresh popup to show updated selection
            marker.openPopup();
          });
        });
      });
    });
  }, [signsData, selectedSignDestinations, onSignDestinationSelect, showSigns]);

  return null;
}

// Component to handle layer control changes for segments and links (mutually exclusive)
function SegmentsLinksLayerControl({
  onSegmentsToggle,
  onLinksToggle
}: {
  onSegmentsToggle: (enabled: boolean) => void;
  onLinksToggle: (enabled: boolean) => void;
}) {
  const map = useMap();

  useEffect(() => {
    const handleOverlayAdd = (e: L.LayersControlEvent) => {
      if (e.name === 'Segmenter') {
        onSegmentsToggle(true);
        // Deactivate links when segments are activated
        onLinksToggle(false);
      }
    };

    const handleOverlayRemove = (e: L.LayersControlEvent) => {
      if (e.name === 'Segmenter') {
        onSegmentsToggle(false);
      }
    };

    map.on('overlayadd', handleOverlayAdd);
    map.on('overlayremove', handleOverlayRemove);

    return () => {
      map.off('overlayadd', handleOverlayAdd);
      map.off('overlayremove', handleOverlayRemove);
    };
  }, [map, onSegmentsToggle, onLinksToggle]);

  return null;
}

// Sync LayersControl overlay toggles with React state
function SignsLayerControl({
  onToggle
}: {
  onToggle: (enabled: boolean) => void;
}) {
  const map = useMap();

  useEffect(() => {
    const handleOverlayAdd = (e: L.LayersControlEvent) => {
      if (e.name === 'Skilt') {
        onToggle(true);
      }
    };

    const handleOverlayRemove = (e: L.LayersControlEvent) => {
      if (e.name === 'Skilt') {
        onToggle(false);
      }
    };

    map.on('overlayadd', handleOverlayAdd);
    map.on('overlayremove', handleOverlayRemove);

    return () => {
      map.off('overlayadd', handleOverlayAdd);
      map.off('overlayremove', handleOverlayRemove);
    };
  }, [map, onToggle]);

  return null;
}

function LinksLayerControl({ onToggle }: { onToggle: (enabled: boolean) => void }) {
  const map = useMap();
  useEffect(() => {
    const handleOverlayAdd = (e: L.LayersControlEvent) => { if (e.name === 'Lenker') onToggle(true); };
    const handleOverlayRemove = (e: L.LayersControlEvent) => { if (e.name === 'Lenker') onToggle(false); };
    map.on('overlayadd', handleOverlayAdd);
    map.on('overlayremove', handleOverlayRemove);
    return () => { map.off('overlayadd', handleOverlayAdd); map.off('overlayremove', handleOverlayRemove); };
  }, [map, onToggle]);
  return null;
}

function AnkerpunkterLayerControl({ onToggle }: { onToggle: (enabled: boolean) => void }) {
  const map = useMap();
  useEffect(() => {
    const handleOverlayAdd = (e: L.LayersControlEvent) => { if (e.name === 'Ankerpunkter') onToggle(true); };
    const handleOverlayRemove = (e: L.LayersControlEvent) => { if (e.name === 'Ankerpunkter') onToggle(false); };
    map.on('overlayadd', handleOverlayAdd);
    map.on('overlayremove', handleOverlayRemove);
    return () => { map.off('overlayadd', handleOverlayAdd); map.off('overlayremove', handleOverlayRemove); };
  }, [map, onToggle]);
  return null;
}

function GrunneierLayerControl({ onToggle }: { onToggle: (enabled: boolean) => void }) {
  const map = useMap();
  useEffect(() => {
    const handleOverlayAdd = (e: L.LayersControlEvent) => { if (e.name === 'Grunneier') onToggle(true); };
    const handleOverlayRemove = (e: L.LayersControlEvent) => { if (e.name === 'Grunneier') onToggle(false); };
    map.on('overlayadd', handleOverlayAdd);
    map.on('overlayremove', handleOverlayRemove);
    return () => { map.off('overlayadd', handleOverlayAdd); map.off('overlayremove', handleOverlayRemove); };
  }, [map, onToggle]);
  return null;
}

// Component to initialize map reference when map is ready
function MapInitializer({
  onMapReady
}: {
  onMapReady: (map: L.Map) => void
}) {
  const map = useMap();

  useEffect(() => {
    debugLog('MapInitializer: map is ready', map);
    onMapReady(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]); // Only depend on map, not onMapReady to avoid re-runs

  return null;
}

function GeomanControl({ onDrawComplete, onEditComplete }: {
  onDrawComplete: (geometry: GeoJSON.LineString) => void;
  onEditComplete: (layerId: string, geometry: GeoJSON.LineString) => void;
}) {
  const map = useMap();

  useEffect(() => {
    if (!map.pm) {
      // Dynamically load Geoman if not available
      import(/* @vite-ignore */ '@geoman-io/leaflet-geoman-free').then(() => {
        if (map.pm) {
          map.pm.setGlobalOptions({
            allowSelfIntersection: false,
            snappable: true,
            snapDistance: 20,
          });
        }
      });
      return;
    }

    // Configure Geoman
    map.pm.setGlobalOptions({
      allowSelfIntersection: false,
      snappable: true,
      snapDistance: 20,
    });

    // Handle draw complete
    map.on('pm:create', (e) => {
      const layer = e.layer;
      if (layer instanceof L.Polyline) {
        const geoJson = layer.toGeoJSON();
        if (geoJson.geometry.type === 'LineString') {
          onDrawComplete(geoJson.geometry as GeoJSON.LineString);
          map.removeLayer(layer);
        }
      }
    });

    // Handle edit complete
    map.on('pm:edit', (e) => {
      const layer = e.layer;
      if (layer instanceof L.Polyline) {
        const geoJson = layer.toGeoJSON();
        if (geoJson.geometry.type === 'LineString') {
          // Get layer ID from feature or fallback to Leaflet ID
          const layerWithFeature = layer as L.Polyline & { feature?: { id?: string | number }; _leaflet_id?: number };
          const layerId = layerWithFeature.feature?.id || layerWithFeature._leaflet_id;
          onEditComplete(String(layerId), geoJson.geometry as GeoJSON.LineString);
        }
      }
    });

    return () => {
      map.off('pm:create');
      map.off('pm:edit');
    };
  }, [map, onDrawComplete, onEditComplete]);

  return null;
}

function SnapLayer({ map, snapManager }: { map: L.Map; snapManager: SnapManager }) {
  useEffect(() => {
    let isDragging = false;
    let snapMarker: L.Marker | null = null;

    const updateSnap = (e: L.LeafletMouseEvent) => {
      if (!isDragging) return;

      const nearest = snapManager.findNearest(e.latlng.lng, e.latlng.lat, map);
      if (nearest) {
        if (!snapMarker) {
          snapMarker = L.marker([nearest.lat, nearest.lon], {
            icon: L.divIcon({
              className: 'snap-marker',
              html: '<div style="width: 12px; height: 12px; border-radius: 50%; background: #2196f3; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);"></div>',
              iconSize: [12, 12],
              iconAnchor: [6, 6],
            }),
          }).addTo(map);
        } else {
          snapMarker.setLatLng([nearest.lat, nearest.lon]);
        }
      } else {
        if (snapMarker) {
          map.removeLayer(snapMarker);
          snapMarker = null;
        }
      }
    };

    map.on('mousedown', () => {
      isDragging = true;
    });

    map.on('mouseup', () => {
      isDragging = false;
      if (snapMarker) {
        map.removeLayer(snapMarker);
        snapMarker = null;
      }
    });

    map.on('mousemove', updateSnap);

    return () => {
      map.off('mousedown');
      map.off('mouseup');
      map.off('mousemove');
      if (snapMarker) {
        map.removeLayer(snapMarker);
      }
    };
  }, [map, snapManager]);

  return null;
}

export function MapView({
  changeset,
  routeGeometry,
  routeNumber,
  selectedRouteNumber,
  onRouteSelect,
  onEventAdded,
  selectedFeatureId,
  selectedFeatureIds = new Set(),
  onFeatureSelect,
  onOpenEditForm,
  localEventsCount = 0,
  signsPrefix,
  signsData: signsDataProp,
  onSignsDataLoad,
  onSignDestinationSelect,
  selectedSignDestinations = new Set(),
  showLinks,
  onShowLinksChange,
  showSegments,
  onShowSegmentsChange,
  showAnchors,
  onShowAnchorsChange,
  showSigns,
  onShowSignsChange,
  showOwnership,
  onShowOwnershipChange,
  editMode,
  onEditModeChange,
  selectedGeometryForOwnership,
  onGeometrySelectForOwnership,
  ownershipData,
  onOwnershipDataChange,
  selectedArea,
}: MapViewProps) {
  const [diffLayer, setDiffLayer] = useState<GeoJSON.FeatureCollection | null>(null);
  const [effectiveLayer, setEffectiveLayer] = useState<GeoJSON.FeatureCollection | null>(null);
  const [showEffective, setShowEffective] = useState(false);
  const [snapManager] = useState(() => new SnapManager());
  const mapRef = useRef<L.Map | null>(null);
  const routeLayerRef = useRef<L.GeoJSON | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [routesInView, setRoutesInView] = useState<GeoJSON.FeatureCollection | null>(null);
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [segmentsData, setSegmentsData] = useState<GeoJSON.FeatureCollection | null>(null);
  const [linksData, setLinksData] = useState<GeoJSON.FeatureCollection | null>(null);
  // Lifted state from App when onSignsDataLoad provided; otherwise local
  const [signsDataLocal, setSignsDataLocal] = useState<SignsReportResponse | null>(null);
  const signsData = signsDataProp !== undefined ? signsDataProp : signsDataLocal;
  const setSignsData = onSignsDataLoad ?? setSignsDataLocal;
  const segmentsLayerRef = useRef<L.GeoJSON | null>(null);
  const linksLayerRef = useRef<L.GeoJSON | null>(null);
  const endpointsLayerRef = useRef<L.LayerGroup | null>(null);
  const signsLayerRef = useRef<L.LayerGroup | null>(null);
  const [anchorNodes, setAnchorNodes] = useState<AnchorNodeInfo[]>([]);
  const [anchorCandidates, setAnchorCandidates] = useState<PlacenameCandidate[]>([]);
  const [anchorFacilities, setAnchorFacilities] = useState<FacilityCandidate[]>([]);
  const [selectedAnchor, setSelectedAnchor] = useState<AnchorNodeInfo | null>(null);
  const [anchorDialogOpen, setAnchorDialogOpen] = useState(false);
  const [anchorSelectedIndex, setAnchorSelectedIndex] = useState<number | null>(null);
  const [anchorManualName, setAnchorManualName] = useState('');
  const [anchorSearchRadius] = useState(1500);

  // When an area is selected, show only anchor nodes that belong to links in that area (linksData is already area-filtered)
  const visibleAnchorNodes = useMemo(() => {
    if (!selectedArea || !linksData?.features?.length) {
      return anchorNodes;
    }
    const nodeIdsInArea = new Set<number>();
    linksData.features.forEach((feature) => {
      const props = feature.properties as { a_node?: number; b_node?: number } | null;
      if (props) {
        if (props.a_node != null) nodeIdsInArea.add(props.a_node);
        if (props.b_node != null) nodeIdsInArea.add(props.b_node);
      }
    });
    return anchorNodes.filter((a) => nodeIdsInArea.has(a.anchor_node_id));
  }, [anchorNodes, linksData, selectedArea]);

  // Segment hover -> route highlight (architecture A)
  const segmentRoutesCacheRef = useRef<Map<string, SegmentRoutesItem[]>>(new Map());
  const routeGeometryCacheRef = useRef<Map<string, GeoJSON.Geometry>>(new Map());
  const routeLengthKmCacheRef = useRef<Map<string, number | null>>(new Map());
  const routeEndpointsCacheRef = useRef<Map<string, { from_name: string | null; to_name: string | null }>>(new Map());
  const linksLayerCacheInvalidateRef = useRef<(() => void) | null>(null);
  const hoveredSegmentLayerRef = useRef<L.Layer | null>(null);
  const [hoveredSegmentId, setHoveredSegmentId] = useState<string | null>(null);
  const [hoverRoutes, setHoverRoutes] = useState<SegmentRoutesItem[]>([]);
  const hoverRoutesRef = useRef<SegmentRoutesItem[]>([]);
  const [hoverRouteIndex, setHoverRouteIndex] = useState(0);
  const hoverRouteIndexRef = useRef(0);
  const [hoverRouteGeometry, setHoverRouteGeometry] = useState<GeoJSON.Geometry | null>(null);

  // Confirmation dialog state
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    variant?: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  } | null>(null);

  // Keep hover refs in sync for stable event handlers
  useEffect(() => {
    hoverRoutesRef.current = hoverRoutes;
  }, [hoverRoutes]);
  useEffect(() => {
    hoverRouteIndexRef.current = hoverRouteIndex;
  }, [hoverRouteIndex]);

  const getRouteLengthKm = useCallback(
    (rutenummer: string): number | null => {
      if (routeLengthKmCacheRef.current.has(rutenummer)) {
        return routeLengthKmCacheRef.current.get(rutenummer) ?? null;
      }
      const match = routesInView?.features?.find((f) => {
        const props = f.properties as { rutenummer?: string; total_length_km?: number | null } | null;
        return props?.rutenummer === rutenummer;
      });
      const km =
        match && typeof (match.properties as any)?.total_length_km === 'number'
          ? ((match.properties as any).total_length_km as number)
          : null;
      routeLengthKmCacheRef.current.set(rutenummer, km);
      return km;
    },
    [routesInView]
  );

  const getRouteGeometryCached = useCallback(
    async (rutenummer: string): Promise<GeoJSON.Geometry | null> => {
      const cached = routeGeometryCacheRef.current.get(rutenummer);
      if (cached) {
        // If geometry is cached but endpoints are not, fetch them
        if (!routeEndpointsCacheRef.current.has(rutenummer)) {
          try {
            const routeData = await api.getRoute(rutenummer, false);
            if (routeData.from_name !== undefined || routeData.to_name !== undefined) {
              routeEndpointsCacheRef.current.set(rutenummer, {
                from_name: routeData.from_name || null,
                to_name: routeData.to_name || null,
              });
            }
          } catch (error) {
            // Silent failure - endpoints are optional
            debugLog('Failed to fetch endpoint names for', rutenummer, error);
          }
        }
        return cached;
      }

      const match = routesInView?.features?.find((f) => {
        const props = f.properties as { rutenummer?: string } | null;
        return props?.rutenummer === rutenummer;
      });
      if (match?.geometry) {
        routeGeometryCacheRef.current.set(rutenummer, match.geometry as GeoJSON.Geometry);
        // Try to fetch endpoint names if not cached
        if (!routeEndpointsCacheRef.current.has(rutenummer)) {
          try {
            const routeData = await api.getRoute(rutenummer, false);
            if (routeData.from_name !== undefined || routeData.to_name !== undefined) {
              routeEndpointsCacheRef.current.set(rutenummer, {
                from_name: routeData.from_name || null,
                to_name: routeData.to_name || null,
              });
            }
          } catch (error) {
            // Silent failure - endpoints are optional
            debugLog('Failed to fetch endpoint names for', rutenummer, error);
          }
        }
        return match.geometry as GeoJSON.Geometry;
      }

      const routeData = await api.getRoute(rutenummer, true);
      const geom = routeData.route_geometry || null;
      if (geom) routeGeometryCacheRef.current.set(rutenummer, geom);
      if (typeof routeData.total_length_km === 'number') {
        routeLengthKmCacheRef.current.set(rutenummer, routeData.total_length_km);
      } else if (typeof routeData.total_length_m === 'number') {
        routeLengthKmCacheRef.current.set(rutenummer, routeData.total_length_m / 1000);
      }
      // Cache endpoint names
      if (routeData.from_name !== undefined || routeData.to_name !== undefined) {
        routeEndpointsCacheRef.current.set(rutenummer, {
          from_name: routeData.from_name || null,
          to_name: routeData.to_name || null,
        });
      }
      return geom;
    },
    [routesInView]
  );

  const ensureHoverTooltip = useCallback((layer: L.Layer) => {
    const anyLayer = layer as any;
    if (!anyLayer.getTooltip || !anyLayer.bindTooltip) return;
    if (!anyLayer.getTooltip()) {
      anyLayer.bindTooltip('', {
        permanent: false,
        sticky: true,
        direction: 'top',
        offset: [0, -10],
        className: 'route-tooltip',
        opacity: 0.95,
      });
    }
  }, []);

  const setHoverTooltip = useCallback((layer: L.Layer, latlng: L.LatLng, html: string) => {
    const anyLayer = layer as any;
    ensureHoverTooltip(layer);
    if (anyLayer.setTooltipContent) {
      anyLayer.setTooltipContent(html);
    }
    if (anyLayer.openTooltip) {
      anyLayer.openTooltip(latlng);
    }
  }, [ensureHoverTooltip]);

  const activateHoverRoute = useCallback(
    async (index: number) => {
      const routes = hoverRoutesRef.current;
      if (!hoveredSegmentId || routes.length === 0) return;

      const safeIndex = ((index % routes.length) + routes.length) % routes.length;
      setHoverRouteIndex(safeIndex);

      const route = routes[safeIndex];
      if (!route?.rutenummer) return;

      try {
        const geom = await getRouteGeometryCached(route.rutenummer);
        setHoverRouteGeometry(geom);
      } catch (error) {
        // Silent failure on hover
        setHoverRouteGeometry(null);
      }

      const layer = hoveredSegmentLayerRef.current;
      if (!layer) return;

      const rowsHtml = routes
        .map((r, i) => {
          const isActive = i === safeIndex;
          const km = r?.rutenummer ? getRouteLengthKm(r.rutenummer) : null;
          const kmStr = typeof km === 'number' ? `${km.toFixed(2)} km` : 'N/A';
          const vha = r.vedlikeholdsansvarlig || '';
          // Get endpoint names from cache
          const endpoints = r.rutenummer ? routeEndpointsCacheRef.current.get(r.rutenummer) : null;
          const fromName = endpoints?.from_name || null;
          const toName = endpoints?.to_name || null;
          let endpointDisplay = '';
          if (fromName && toName) {
            endpointDisplay = `${fromName} → ${toName}`;
          } else if (fromName || toName) {
            endpointDisplay = fromName || toName || '';
          } else {
            // Fallback to route name if endpoints not available
            endpointDisplay = r.rutenavn || 'Uten navn';
          }
          return `
            <div style="margin-top:${i === 0 ? 0 : 6}px;">
              <div><strong>${isActive ? '▶ ' : ''}${r.rutenummer}</strong>${isActive ? ` <span style="opacity:0.75">(${safeIndex + 1}/${routes.length})</span>` : ''}</div>
              <div style="opacity:0.9">${endpointDisplay}</div>
              <div style="opacity:0.85">${kmStr}${vha ? ` • ${vha}` : ''}</div>
            </div>
          `;
        })
        .join('');

      // LatLng is updated on mousemove; openTooltip uses last mousemove latlng if possible
      const anyLayer = layer as any;
      const lastLatLng: L.LatLng | null = anyLayer?._tooltip?._latlng ?? null;
      const latlng = lastLatLng ?? (mapRef.current ? mapRef.current.getCenter() : new L.LatLng(0, 0));
      setHoverTooltip(
        layer,
        latlng,
        `
          <div style="font-size:12px; line-height:1.35;">
            <div style="opacity:0.8; margin-bottom:6px;">Segment ${hoveredSegmentId} • Bytt rute med ← / →</div>
            ${rowsHtml}
          </div>
        `
      );
    },
    [getRouteGeometryCached, getRouteLengthKm, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, hoveredSegmentId, setHoverTooltip]
  );

  const handleSegmentHoverStart = useCallback(
    (_segmentId: string, _layer: L.Layer, _latlng: L.LatLng) => {
      // Segment hover highlighting is now handled via links/rutes, so this is a no-op.
    },
    []
  );

  const handleSegmentHoverMove = useCallback((segmentId: string, layer: L.Layer, latlng: L.LatLng) => {
    if (!hoveredSegmentId || hoveredSegmentId !== segmentId) return;
    const anyLayer = layer as any;
    if (anyLayer.openTooltip) {
      anyLayer.openTooltip(latlng);
    }
  }, [hoveredSegmentId]);

  const handleSegmentHoverEnd = useCallback((segmentId: string, layer: L.Layer) => {
    if (hoveredSegmentId !== segmentId) return;
    const anyLayer = layer as any;
    if (anyLayer.closeTooltip) anyLayer.closeTooltip();
    hoveredSegmentLayerRef.current = null;
    setHoveredSegmentId(null);
    setHoverRoutes([]);
    setHoverRouteIndex(0);
    setHoverRouteGeometry(null);
  }, [hoveredSegmentId]);

  // Keyboard cycling while hovering a segment
  useEffect(() => {
    if (!hoveredSegmentId) return;
    const onKeyDown = (e: KeyboardEvent) => {
      const routes = hoverRoutesRef.current;
      if (!routes || routes.length <= 1) return;
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        activateHoverRoute(hoverRouteIndexRef.current + 1);
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        activateHoverRoute(hoverRouteIndexRef.current - 1);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [activateHoverRoute, hoveredSegmentId]);

  // Load routes in viewport - only when Links layer is on (routes are used for link popups / route selector)
  useEffect(() => {
    debugLog('Routes useEffect triggered:', { mapReady, mapRef: !!mapRef.current, selectedArea, showLinks });

    if (!showLinks) {
      setRoutesInView(null);
      return;
    }
    if (!mapRef.current || !mapReady) {
      debugLog('Skipping routes load - map not ready');
      return;
    }

    let requestId = 0;
    let activeController: AbortController | null = null;
    let debounceTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let initialLoadTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let lastBbox: string | null = null;
    const DEBOUNCE_DELAY = 300; // ms - delay before making API call after map movement stops

    // Helper to calculate bounding box from GeoJSON features
    const calculateBbox = (features: GeoJSON.Feature[]): L.LatLngBounds | null => {
      if (features.length === 0) return null;

      let minLat = Infinity;
      let minLng = Infinity;
      let maxLat = -Infinity;
      let maxLng = -Infinity;

      const processGeometry = (geom: GeoJSON.Geometry) => {
        if (geom.type === 'Point') {
          const [lng, lat] = geom.coordinates;
          minLat = Math.min(minLat, lat);
          minLng = Math.min(minLng, lng);
          maxLat = Math.max(maxLat, lat);
          maxLng = Math.max(maxLng, lng);
        } else if (geom.type === 'LineString' || geom.type === 'MultiPoint') {
          for (const coord of geom.coordinates) {
            const [lng, lat] = coord;
            minLat = Math.min(minLat, lat);
            minLng = Math.min(minLng, lng);
            maxLat = Math.max(maxLat, lat);
            maxLng = Math.max(maxLng, lng);
          }
        } else if (geom.type === 'Polygon' || geom.type === 'MultiLineString') {
          for (const ring of geom.coordinates) {
            for (const coord of ring) {
              const [lng, lat] = coord;
              minLat = Math.min(minLat, lat);
              minLng = Math.min(minLng, lng);
              maxLat = Math.max(maxLat, lat);
              maxLng = Math.max(maxLng, lng);
            }
          }
        } else if (geom.type === 'MultiPolygon') {
          for (const polygon of geom.coordinates) {
            for (const ring of polygon) {
              for (const coord of ring) {
                const [lng, lat] = coord;
                minLat = Math.min(minLat, lat);
                minLng = Math.min(minLng, lng);
                maxLat = Math.max(maxLat, lat);
                maxLng = Math.max(maxLng, lng);
              }
            }
          }
        }
      };

      for (const feature of features) {
        if (feature.geometry) {
          processGeometry(feature.geometry);
        }
      }

      if (minLat === Infinity) return null;

      return L.latLngBounds([minLat, minLng], [maxLat, maxLng]);
    };

    const loadRoutesInView = async () => {
      if (!mapRef.current) {
        debugLog('mapRef.current is null in loadRoutesInView');
        return;
      }

      requestId += 1;
      const currentRequestId = requestId;

      // Abort any pending request
      if (activeController) {
        activeController.abort();
        activeController = null;
      }
      activeController = new AbortController();

      try {
        let data: RoutesResponse;

        if (selectedArea) {
          // Load routes by area prefix
          debugLog('Loading routes by area prefix:', selectedArea);
          data = await api.listRoutes({ prefix: selectedArea, limit: 1000, include_geometry: true }, { signal: activeController.signal });
        } else {
          // Load routes by bounding box (original behavior)
          const bounds = mapRef.current.getBounds();
          const zoom = mapRef.current.getZoom();
          const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

          // Request deduplication: skip if bbox hasn't changed
          if (bbox === lastBbox) {
            debugLog('Skipping duplicate bbox request:', bbox);
            return;
          }
          lastBbox = bbox;

          debugLog('Loading routes in bbox:', { bbox, zoom });
          data = await api.getRoutesInBbox(bbox, { signal: activeController.signal });
        }

        // Ignore response if it's outdated (newer request was made)
        if (currentRequestId !== requestId) {
          debugLog('Ignoring outdated response for request', currentRequestId);
          return;
        }

        const totalRoutes = data.total ?? 0;
        const returnedRoutes = data.routes?.length || 0;

        debugLog('Routes API response:', {
          total: totalRoutes,
          returned: returnedRoutes,
          selectedArea,
        });

        // Convert routes to GeoJSON FeatureCollection
        const features: GeoJSON.Feature[] = (data.routes || [])
          .map((route) => {
            // Type assertion: routes from API may have route_geometry and total_length_m
            const routeWithGeometry = route as RouteInfo & {
              route_geometry?: GeoJSON.Geometry | null;
              total_length_m?: number;
              total_length_km?: number;
            };
            const geometry = routeWithGeometry.route_geometry;
            if (!geometry) {
              return null;
            }
            // Calculate length in km if available
            const lengthKm = routeWithGeometry.total_length_km
              ?? (routeWithGeometry.total_length_m ? routeWithGeometry.total_length_m / 1000 : null);
            return {
              type: 'Feature' as const,
              id: route.rutenummer,
              geometry: geometry,
              properties: {
                rutenummer: route.rutenummer,
                rutenavn: route.rutenavn,
                vedlikeholdsansvarlig: route.vedlikeholdsansvarlig,
                total_length_km: lengthKm,
              },
            } as GeoJSON.Feature;
          })
          .filter((f): f is GeoJSON.Feature => f !== null);

        const filteredFeatures = features.filter((f) => f.geometry !== null && f.geometry !== undefined);
        debugLog(`Loaded ${filteredFeatures.length} routes with geometry (out of ${totalRoutes} total)`);

        setRoutesInView({
          type: 'FeatureCollection',
          features: filteredFeatures,
        });

        // If area is selected, center map on routes
        if (selectedArea && mapRef.current && filteredFeatures.length > 0) {
          const bbox = calculateBbox(filteredFeatures);
          if (bbox) {
            // Add some padding
            mapRef.current.fitBounds(bbox, { padding: [50, 50] });
            debugLog('Centered map on area routes');
          }
        }
      } catch (error) {
        if (isAbortError(error)) {
          debugLog('Request aborted');
          return;
        }
        // Don't show notification for background route loading - just log silently
        // Errors are logged by handleApiError
      } finally {
        // Clear controller after request completes
        if (currentRequestId === requestId) {
          activeController = null;
        }
      }
    };

    // Debounced version that waits for map movement to stop
    const debouncedLoadRoutes = () => {
      // If area is selected, don't reload on map movement
      if (selectedArea) {
        return;
      }

      // Clear any existing debounce timer
      if (debounceTimeoutId) {
        clearTimeout(debounceTimeoutId);
        debounceTimeoutId = null;
      }

      // Abort any pending request when new movement starts
      if (activeController) {
        activeController.abort();
        activeController = null;
      }

      // Set new debounce timer
      debounceTimeoutId = setTimeout(() => {
        debounceTimeoutId = null;
        loadRoutesInView();
      }, DEBOUNCE_DELAY);
    };

    // Load routes on map move/zoom (with debouncing) - only if no area is selected
    if (!selectedArea) {
      mapRef.current.on('moveend', debouncedLoadRoutes);
      mapRef.current.on('zoomend', debouncedLoadRoutes);
    }

    // Initial load with a small delay to ensure map is fully initialized
    initialLoadTimeoutId = setTimeout(() => {
      debugLog('Initial routes load');
      loadRoutesInView();
    }, 500);

    return () => {
      if (debounceTimeoutId) {
        clearTimeout(debounceTimeoutId);
      }
      if (initialLoadTimeoutId) {
        clearTimeout(initialLoadTimeoutId);
      }
      if (activeController) {
        activeController.abort();
      }
      if (mapRef.current) {
        mapRef.current.off('moveend', debouncedLoadRoutes);
        mapRef.current.off('zoomend', debouncedLoadRoutes);
      }
    };
  }, [mapReady, selectedArea, showLinks]);


  // Load segments and links - by route if selected, otherwise by bbox in inspection mode
  useEffect(() => {
    if (!mapReady) {
      return;
    }

    // In edit mode, require route selection
    if (editMode && !routeNumber) {
      setSegmentsData(null);
      setLinksData(null);
      onShowSegmentsChange(false);
      onShowLinksChange(false);
      setAnchorNodes([]);
      return;
    }

    // When links layer is on, load links by bbox (routes are logical layer on top)
    if (showLinks && mapRef.current) {
      const bounds = mapRef.current.getBounds();
      const bbox = {
        xmin: bounds.getWest(),
        ymin: bounds.getSouth(),
        xmax: bounds.getEast(),
        ymax: bounds.getNorth(),
      };

      const linksController = new AbortController();

      // Load links by bbox with optional area prefix filter
      api.getLinksByBbox(bbox, 500, selectedArea || null, { signal: linksController.signal })
        .then(async (data: GeoJSON.FeatureCollection) => {
          debugLog('Links by bbox API response:', data);
          setLinksData(data);

          // Pre-fetch route info for all unique routes in links (bulk fetch)
          if (data.features && data.features.length > 0) {
            const uniqueRouteNumbers = new Set<string>();
            data.features.forEach((feature) => {
              const props = feature.properties as {
                routes?: { rutenummer?: string }[];
                [key: string]: unknown;
              } | null;
              if (props?.routes) {
                props.routes.forEach((r) => {
                  if (r.rutenummer) {
                    uniqueRouteNumbers.add(r.rutenummer);
                  }
                });
              }
            });

            // Bulk fetch is now handled in LinksLayer component when linksData changes
          }
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          const appError = handleApiError(error, 'Load Links');
          notificationManager.warning(`Kunne ikke laste linker: ${appError.message}`);
        });

      // Note: Segments don't have a bbox endpoint yet, so we skip them when no route is selected
      setSegmentsData(null);
      // Anchor nodes are loaded only by the "reload anchors by bbox on move/zoom" effect when showAnchors && !routeNumber

      return () => {
        linksController.abort();
      };
    }

    // Don't clear anchors in inspection mode - they should always be loaded
    // Only clear when switching away from inspection/anchor-naming modes
    if (!showAnchors) {
      setAnchorNodes([]);
    }

    // Load by route if route is selected
    if (!routeNumber) {
      return;
    }

    // Reset segment layer while loading new route data
    onShowSegmentsChange(false);

    const segmentsController = new AbortController();
    const linksController = new AbortController();

    // Load segments
    api.getRouteSegments(routeNumber, true, { signal: segmentsController.signal })
      .then((data: RouteSegmentsResponse) => {
        debugLog('Segments API response:', data);
        const features: GeoJSON.Feature[] = (data.segments || [])
          .map((seg) => {
            // API returns geometry as 'senterlinje' not 'geometry'
            // and uses 'segment_objid' not 'objid'
            const geometry = seg.senterlinje || seg.geometry;
            const segmentId = seg.segment_objid || seg.objid;
            if (!geometry || segmentId === undefined) {
              return null;
            }
            return {
              type: 'Feature' as const,
              id: segmentId,
              geometry: geometry,
              properties: {
                objid: segmentId,
                rutenummer: seg.rutenummer,
                rutenavn: seg.rutenavn || null,
                length_m: seg.length_meters || seg.length_m || null,
              },
            } as GeoJSON.Feature;
          })
          .filter((f): f is GeoJSON.Feature => f !== null);
        const filteredFeatures = features.filter((f) => f.geometry !== null && f.geometry !== undefined);
        debugLog(`Loaded ${filteredFeatures.length} segments with geometry (out of ${features.length} total)`);
        if (filteredFeatures.length === 0 && features.length > 0) {
          console.warn('No segments with geometry found. First segment:', data.segments?.[0]);
        }
        setSegmentsData({
          type: 'FeatureCollection',
          features: filteredFeatures,
        });
      })
      .catch(error => {
        if (isAbortError(error)) return;
        const appError = handleApiError(error, 'Load Segments');
        notificationManager.warning(`Kunne ikke laste segmenter: ${appError.message}`);
      });

    // Load links
    api.getRouteLinks(routeNumber, true, { signal: linksController.signal })
      .then((data: RouteLinksResponse) => {
        debugLog('Links API response:', data);
        const features: GeoJSON.Feature[] = (data.links || [])
          .map((link) => {
            // API returns geometry as 'geom' not 'geometry'
            const geometry = link.geom || link.geometry || link.senterlinje;
            if (!geometry) {
              return null;
            }
            return {
              type: 'Feature' as const,
              id: link.link_id,
              geometry: geometry,
              properties: {
                link_id: link.link_id,
                a_node: link.a_node,
                b_node: link.b_node,
                length_m: link.length_m || link.length_meters || null,
              },
            } as GeoJSON.Feature;
          })
          .filter((f): f is GeoJSON.Feature => f !== null);
        const filteredFeatures = features.filter((f) => f.geometry !== null && f.geometry !== undefined);
        debugLog(`Loaded ${filteredFeatures.length} links with geometry (out of ${features.length} total)`);
        if (filteredFeatures.length === 0 && features.length > 0) {
          console.warn('No links with geometry found. First link:', data.links?.[0]);
        }
        setLinksData({
          type: 'FeatureCollection',
          features: filteredFeatures,
        });
      })
      .catch(error => {
        if (isAbortError(error)) return;
        const appError = handleApiError(error, 'Load Links');
        notificationManager.warning(`Kunne ikke laste lenker: ${appError.message}`);
      });

    // Load anchor nodes for the route when anchors layer is on
    if (showAnchors) {
      api.getRouteAnchors(routeNumber, { signal: linksController.signal })
        .then((data) => {
          const anchors: AnchorNodeInfo[] = (data.anchors || []).map((anchor) => ({
            anchor_node_id: anchor.anchor_node_id,
            coordinates: anchor.coordinates || [0, 0],
            name: anchor.name || null,
            link_count: anchor.link_count || 0,
          }));
          setAnchorNodes(anchors);
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          // Silently fail - anchors are optional
        });
    }

    return () => {
      segmentsController.abort();
      linksController.abort();
    };
  }, [routeNumber, mapReady, showAnchors, onShowSegmentsChange]);

  // Reload links by bbox when map moves/zooms when links layer on and no route selected
  useEffect(() => {
    if (!mapReady || !mapRef.current || !showLinks || routeNumber) {
      return;
    }

    let debounceTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let initialLoadTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let activeController: AbortController | null = null;
    let lastBbox: string | null = null;
    const DEBOUNCE_DELAY = 300; // ms

    const loadLinksInView = () => {
      const bounds = mapRef.current?.getBounds();
      if (!bounds) return;

      const bbox = {
        xmin: bounds.getWest(),
        ymin: bounds.getSouth(),
        xmax: bounds.getEast(),
        ymax: bounds.getNorth(),
      };

      // Request deduplication: skip if bbox hasn't changed
      const bboxStr = `${bbox.xmin},${bbox.ymin},${bbox.xmax},${bbox.ymax}`;
      if (bboxStr === lastBbox) {
        debugLog('Skipping duplicate links bbox request:', bboxStr);
        return;
      }
      lastBbox = bboxStr;

      // Abort any pending request
      if (activeController) {
        activeController.abort();
        activeController = null;
      }
      activeController = new AbortController();

      api.getLinksByBbox(bbox, 500, selectedArea || null, { signal: activeController.signal })
        .then((data: GeoJSON.FeatureCollection) => {
          if (data) {
            setLinksData(data);
          }
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          const appError = handleApiError(error, 'Load Links');
          notificationManager.warning(`Kunne ikke laste linker: ${appError.message}`);
        })
        .finally(() => {
          activeController = null;
        });
    };

    // Debounced version that waits for map movement to stop
    const debouncedLoadLinks = () => {
      // Clear any existing debounce timer
      if (debounceTimeoutId) {
        clearTimeout(debounceTimeoutId);
        debounceTimeoutId = null;
      }

      // Abort any pending request when new movement starts
      if (activeController) {
        activeController.abort();
        activeController = null;
      }

      // Set new debounce timer
      debounceTimeoutId = setTimeout(() => {
        debounceTimeoutId = null;
        loadLinksInView();
      }, DEBOUNCE_DELAY);
    };

    mapRef.current.on('moveend', debouncedLoadLinks);
    mapRef.current.on('zoomend', debouncedLoadLinks);

    // Initial load with a small delay
    initialLoadTimeoutId = setTimeout(() => {
      loadLinksInView();
    }, 300);

    return () => {
      if (debounceTimeoutId) {
        clearTimeout(debounceTimeoutId);
      }
      if (initialLoadTimeoutId) {
        clearTimeout(initialLoadTimeoutId);
      }
      if (activeController) {
        activeController.abort();
      }
      if (mapRef.current) {
        mapRef.current.off('moveend', debouncedLoadLinks);
        mapRef.current.off('zoomend', debouncedLoadLinks);
      }
    };
  }, [mapReady, showLinks, routeNumber, selectedArea, editMode, onShowSegmentsChange, onShowLinksChange]);

  // Reload anchors by bbox when map moves/zooms when anchors layer on and no route selected
  useEffect(() => {
    if (!mapReady || !mapRef.current || !showAnchors || routeNumber) {
      return;
    }

    let debounceTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let initialLoadTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let activeController: AbortController | null = null;
    let lastBbox: string | null = null;
    const DEBOUNCE_DELAY = 300; // ms

    const loadAnchorsInView = () => {
      const bounds = mapRef.current?.getBounds();
      if (!bounds) return;

      const bbox = {
        xmin: bounds.getWest(),
        ymin: bounds.getSouth(),
        xmax: bounds.getEast(),
        ymax: bounds.getNorth(),
      };

      // Request deduplication: skip if bbox hasn't changed
      const bboxStr = `${bbox.xmin},${bbox.ymin},${bbox.xmax},${bbox.ymax}`;
      if (bboxStr === lastBbox) {
        debugLog('Skipping duplicate anchors bbox request:', bboxStr);
        return;
      }
      lastBbox = bboxStr;

      // Abort any pending request
      if (activeController) {
        activeController.abort();
        activeController = null;
      }
      activeController = new AbortController();

      api.getAnchorsByBbox(bbox, 500, { signal: activeController.signal })
        .then((data: GeoJSON.FeatureCollection) => {
          const anchors: AnchorNodeInfo[] = (data.features || []).map((feature) => {
            const props = feature.properties || {};
            const geometry = feature.geometry;
            let coordinates: [number, number] = [0, 0];
            if (geometry && geometry.type === 'Point' && geometry.coordinates) {
              coordinates = [geometry.coordinates[0], geometry.coordinates[1]];
            }
            return {
              anchor_node_id: props.node_id as number || parseInt(String(feature.id || '0'), 10),
              coordinates,
              name: props.navn ? {
                name: String(props.navn),
                source_type: String(props.navn_kilde || 'unknown'),
                distance_meters: props.navn_distance_m ? Number(props.navn_distance_m) : null,
              } : null,
              link_count: 0,
            };
          });
          setAnchorNodes(anchors);
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          // Silently fail
        })
        .finally(() => {
          activeController = null;
        });
    };

    // Debounced version that waits for map movement to stop
    const debouncedLoadAnchors = () => {
      // Clear any existing debounce timer
      if (debounceTimeoutId) {
        clearTimeout(debounceTimeoutId);
        debounceTimeoutId = null;
      }

      // Abort any pending request when new movement starts
      if (activeController) {
        activeController.abort();
        activeController = null;
      }

      // Set new debounce timer
      debounceTimeoutId = setTimeout(() => {
        debounceTimeoutId = null;
        loadAnchorsInView();
      }, DEBOUNCE_DELAY);
    };

    mapRef.current.on('moveend', debouncedLoadAnchors);
    mapRef.current.on('zoomend', debouncedLoadAnchors);

    // Initial load
    initialLoadTimeoutId = setTimeout(() => {
      loadAnchorsInView();
    }, 300);

    return () => {
      if (debounceTimeoutId) {
        clearTimeout(debounceTimeoutId);
      }
      if (initialLoadTimeoutId) {
        clearTimeout(initialLoadTimeoutId);
      }
      if (activeController) {
        activeController.abort();
      }
      if (mapRef.current) {
        mapRef.current.off('moveend', debouncedLoadAnchors);
        mapRef.current.off('zoomend', debouncedLoadAnchors);
      }
    };
  }, [mapReady, showAnchors, routeNumber]);

  // Load anchor nodes for selected route when anchors layer on
  useEffect(() => {
    if (!routeNumber || !mapReady) {
      if (!showAnchors) {
        setAnchorNodes([]);
      }
      return;
    }
    if (!showAnchors) {
      setAnchorNodes([]);
      return;
    }

    const controller = new AbortController();
    api.getRouteAnchors(routeNumber, { signal: controller.signal })
      .then((data) => {
        setAnchorNodes(data.anchors || []);
      })
      .catch((error) => {
        if (isAbortError(error)) return;
        const appError = handleApiError(error, 'Load Anchor Nodes');
        notificationManager.warning(`Kunne ikke laste ankernoder: ${appError.message}`);
      });

    return () => {
      controller.abort();
    };
  }, [routeNumber, mapReady, showAnchors]);

  // Load signs data when layer is enabled - based on route, area/prefix, or map viewport (bbox)
  useEffect(() => {
    if (!showSigns || !mapReady || !mapRef.current) {
      if (!showSigns) {
        setSignsData(null);
      }
      return;
    }

    const controller = new AbortController();
    const map = mapRef.current;

    // Priority: route > selectedArea/signsPrefix > bbox (map viewport)
    const areaOrPrefix = selectedArea ?? signsPrefix;
    const usePrefix = areaOrPrefix && areaOrPrefix.trim().length >= 2;
    let loadPromise: Promise<SignsReportResponse | null>;

    if (routeNumber) {
      loadPromise = api.getRouteSigns(routeNumber, { signal: controller.signal });
    } else if (usePrefix) {
      loadPromise = api.getSignsByPrefix(areaOrPrefix!.trim(), { signal: controller.signal });
    } else {
      const bounds = map.getBounds();
      const bbox = {
        xmin: bounds.getWest(),
        ymin: bounds.getSouth(),
        xmax: bounds.getEast(),
        ymax: bounds.getNorth(),
      };
      loadPromise = api.getSignsByBbox(bbox, { signal: controller.signal });
    }

    loadPromise
      .then((data) => {
        if (data) {
          setSignsData(data);
        }
      })
      .catch((error) => {
        if (isAbortError(error)) return;
        const appError = handleApiError(error, 'Load Signs');
        notificationManager.warning(`Kunne ikke laste skilt: ${appError.message}`);
      });

    return () => {
      controller.abort();
    };
  }, [showSigns, mapReady, routeNumber, selectedArea, signsPrefix, setSignsData]);

  // Reload signs when map moves/zooms (debounced) - only when NOT using area/prefix (bbox mode)
  useEffect(() => {
    if (!showSigns || !mapReady || !mapRef.current) {
      return;
    }

    // When area or prefix is selected, signs are loaded by prefix once; do not overwrite with bbox on pan/zoom
    const areaOrPrefix = selectedArea ?? signsPrefix;
    const usePrefix = areaOrPrefix && areaOrPrefix.trim().length >= 2;
    if (routeNumber || usePrefix) {
      return;
    }

    const DEBOUNCE_MS = 300;
    let debounceId: ReturnType<typeof setTimeout> | null = null;
    let activeController: AbortController | null = null;

    const loadSignsInView = () => {
      const bounds = mapRef.current?.getBounds();
      if (!bounds) return;
      if (activeController) {
        activeController.abort();
      }
      activeController = new AbortController();
      const bbox = {
        xmin: bounds.getWest(),
        ymin: bounds.getSouth(),
        xmax: bounds.getEast(),
        ymax: bounds.getNorth(),
      };
      api.getSignsByBbox(bbox, { signal: activeController.signal })
        .then((data) => {
          if (data) {
            setSignsData(data);
          }
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          const appError = handleApiError(error, 'Load Signs');
          notificationManager.warning(`Kunne ikke laste skilt: ${appError.message}`);
        })
        .finally(() => {
          activeController = null;
        });
    };

    const debouncedLoad = () => {
      if (debounceId) clearTimeout(debounceId);
      if (activeController) {
        activeController.abort();
        activeController = null;
      }
      debounceId = setTimeout(() => {
        debounceId = null;
        loadSignsInView();
      }, DEBOUNCE_MS);
    };

    mapRef.current.on('moveend', debouncedLoad);
    mapRef.current.on('zoomend', debouncedLoad);

    // Initial load after a short delay
    debounceId = setTimeout(() => {
      debounceId = null;
      loadSignsInView();
    }, DEBOUNCE_MS);

    return () => {
      if (debounceId) clearTimeout(debounceId);
      if (activeController) activeController.abort();
      if (mapRef.current) {
        mapRef.current.off('moveend', debouncedLoad);
        mapRef.current.off('zoomend', debouncedLoad);
      }
    };
  }, [showSigns, mapReady, routeNumber, selectedArea, signsPrefix, setSignsData]);

  // Display selected route geometry on map (highlighted)
  useEffect(() => {
    if (!mapRef.current || !mapReady) return;

    // Clear previous selected route layer
    if (routeLayerRef.current) {
      mapRef.current.removeLayer(routeLayerRef.current);
      routeLayerRef.current = null;
    }

    // Display selected route geometry if available
    if (routeGeometry && routeNumber === selectedRouteNumber) {
      const routeLayer = L.geoJSON(routeGeometry, {
        style: {
          color: '#e74c3c',
          weight: 6,
          opacity: 1.0,
        },
      }).addTo(mapRef.current);

      // Add popup
      if (routeNumber) {
        routeLayer.bindPopup(`<strong>${routeNumber}</strong>`);
      }

      // Zoom to route
      const bounds = routeLayer.getBounds();
      if (bounds && bounds.isValid()) {
        mapRef.current.fitBounds(bounds, { padding: [50, 50] });
      }

      routeLayerRef.current = routeLayer;
    }
  }, [routeGeometry, routeNumber, selectedRouteNumber, mapReady]);

  // Segments and links are now handled by SegmentsLayer and LinksLayer components in LayersControl
  // Style updates are handled within those components when selection changes

  // Links are now handled by LinksLayer component in LayersControl
  // Style updates are handled within that component when selection changes

  const openAnchorDialog = useCallback((anchor: AnchorNodeInfo) => {
    setSelectedAnchor(anchor);
    setAnchorDialogOpen(true);
    setAnchorCandidates([]);
    setAnchorFacilities([]);
    setAnchorSelectedIndex(null);
    setAnchorManualName('');

    api.getAnchorPlacenames(anchor.anchor_node_id, anchorSearchRadius, 10)
      .then((data) => {
        setAnchorCandidates(data.candidates || []);
        setAnchorFacilities(data.facilities || []);
      })
      .catch((error) => {
        const appError = handleApiError(error, 'Load Placenames');
        notificationManager.warning(`Kunne ikke hente stedsnavn: ${appError.message}`);
      });
  }, [anchorSearchRadius]);

  // Display endpoints (for segments and links)
  useEffect(() => {
    if (!mapRef.current || !mapReady) {
      if (endpointsLayerRef.current && mapRef.current) {
        mapRef.current.removeLayer(endpointsLayerRef.current);
        endpointsLayerRef.current = null;
      }
      return;
    }

    // Show endpoints layer when anchors layer on, or when segments/links are shown
    if (!showAnchors && !showSegments && !showLinks) {
      if (endpointsLayerRef.current) {
        mapRef.current.removeLayer(endpointsLayerRef.current);
        endpointsLayerRef.current = null;
      }
      return;
    }

    // Clear previous endpoints
    if (endpointsLayerRef.current) {
      mapRef.current.removeLayer(endpointsLayerRef.current);
      endpointsLayerRef.current = null;
    }

    const endpointsGroup = L.layerGroup().addTo(mapRef.current);
    const endpointSet = new Set<string>(); // To avoid duplicate endpoints
    const linkEndpointSet = new Set<string>(); // Keep link endpoints visible even when shared
    const linkEndpointCounts = new Map<string, number>();
    const linkEndpointCoords = new Map<string, number[]>();

    // Create a map of anchor coordinates for quick lookup (key: "lon,lat", value: anchor)
    const anchorCoordMap = new Map<string, AnchorNodeInfo>();
    if (visibleAnchorNodes.length > 0) {
      visibleAnchorNodes.forEach((anchor) => {
        const [lon, lat] = anchor.coordinates;
        const key = `${lon},${lat}`;
        anchorCoordMap.set(key, anchor);
      });
    }

    // Helper function to check if coordinates match an anchor (with tolerance for floating point)
    const findAnchorAtCoord = (lon: number, lat: number): AnchorNodeInfo | null => {
      // Check exact match first
      const exactKey = `${lon},${lat}`;
      if (anchorCoordMap.has(exactKey)) {
        return anchorCoordMap.get(exactKey)!;
      }
      // Check with small tolerance (0.000001 degrees ≈ 0.1m)
      const tolerance = 0.000001;
      for (const [key, anchor] of anchorCoordMap.entries()) {
        const [anchorLon, anchorLat] = anchor.coordinates;
        if (Math.abs(anchorLon - lon) < tolerance && Math.abs(anchorLat - lat) < tolerance) {
          return anchor;
        }
      }
      return null;
    };

    if (!mapRef.current.getPane('link-endpoints')) {
      const pane = mapRef.current.createPane('link-endpoints');
      pane.style.zIndex = '650';
    }

    // Add endpoints from segments
    if (showSegments && segmentsData) {
      segmentsData.features.forEach((feature) => {
        if (feature.geometry.type === 'LineString') {
          const coords = feature.geometry.coordinates;
          if (coords.length > 0) {
            // Start point
            const startKey = `${coords[0][0]},${coords[0][1]}`;
            if (!endpointSet.has(startKey)) {
              endpointSet.add(startKey);
              L.circleMarker([coords[0][1], coords[0][0]], {
                radius: 6,
                fillColor: '#9b59b6',
                color: '#fff',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.8,
              }).addTo(endpointsGroup);
            }
            // End point
            const endKey = `${coords[coords.length - 1][0]},${coords[coords.length - 1][1]}`;
            if (!endpointSet.has(endKey)) {
              endpointSet.add(endKey);
              L.circleMarker([coords[coords.length - 1][1], coords[coords.length - 1][0]], {
                radius: 6,
                fillColor: '#9b59b6',
                color: '#fff',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.8,
              }).addTo(endpointsGroup);
            }
          }
        }
      });
    }


    // Add anchor node markers when anchors layer is on (visibleAnchorNodes filters by selected area)
    if (showAnchors && visibleAnchorNodes.length > 0) {
      visibleAnchorNodes.forEach((anchor) => {
        const [lon, lat] = anchor.coordinates;
        const nameLabel = anchor.name?.name || `Anchor ${anchor.anchor_node_id}`;
        const hasName = !!anchor.name?.name;

        const marker = L.circleMarker([lat, lon], {
          radius: 8,
          fillColor: '#6b7280',
          color: '#ffffff',
          weight: 2,
          opacity: 1,
          fillOpacity: 0.8,
          pane: 'link-endpoints',
        }).addTo(endpointsGroup);

        marker.bindTooltip(
          !hasName ? `${nameLabel} (mangler navn)` : nameLabel,
          {
            permanent: false,
            direction: 'top',
            className: 'link-midpoint-label',
            opacity: 0.9,
            interactive: false,
            sticky: true,
          }
        );

        // Click handler for anchor naming dialog
        marker.on('click', () => openAnchorDialog(anchor));
      });
    }


    endpointsLayerRef.current = endpointsGroup;
    // Note: openAnchorDialog is intentionally not in dependencies as it's stable (uses stable state setters and constant anchorSearchRadius)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showSegments, showLinks, showAnchors, segmentsData, linksData, mapReady, visibleAnchorNodes]);

  // Signs markers are now handled by the SignsLayer component in LayersControl

  // Load layers
  useEffect(() => {
    if (!changeset || !mapReady) {
      if (!changeset) {
        setDiffLayer(null);
        setEffectiveLayer(null);
      }
      return;
    }

    // Load diff layer
    api.getDiffGeoJSON(changeset.id)
      .then(setDiffLayer)
      .catch((error) => {
        const appError = handleApiError(error, 'Load Diff Layer');
        notificationManager.error(`Kunne ikke laste diff layer: ${appError.message}`);
      });

    // Load effective layer
    api.getEffectiveGeoJSON(changeset.id)
      .then(setEffectiveLayer)
      .catch((error) => {
        const appError = handleApiError(error, 'Load Effective Layer');
        notificationManager.error(`Kunne ikke laste effective layer: ${appError.message}`);
      });

    // Load snap targets when map moves
    const updateSnapTargets = () => {
      if (!mapRef.current) return;
      const bounds = mapRef.current.getBounds();
      const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
      api.getSnapTargets(bbox)
        .then((data) => snapManager.loadTargets(data.targets))
        .catch((error) => {
          const appError = handleApiError(error, 'Load Snap Targets');
          // Don't show notification for background snap target loading
          // notificationManager.warning(`Kunne ikke laste snap targets: ${appError.message}`);
        });
    };

    if (mapRef.current) {
      mapRef.current.on('moveend', updateSnapTargets);
      updateSnapTargets();
    }

    return () => {
      if (mapRef.current) {
        mapRef.current.off('moveend', updateSnapTargets);
      }
    };
  }, [changeset?.id, snapManager, mapReady]);

  // Update cursor when split mode is active
  useEffect(() => {
    if (!mapRef.current) return;

    const mapContainer = mapRef.current.getContainer();
    if (activeTool === 'split') {
      mapContainer.style.cursor = 'crosshair';
    } else {
      mapContainer.style.cursor = '';
    }

    return () => {
      if (mapContainer) {
        mapContainer.style.cursor = '';
      }
    };
  }, [activeTool]);

  const closeAnchorDialog = () => {
    setAnchorDialogOpen(false);
    setSelectedAnchor(null);
    setAnchorCandidates([]);
    setAnchorFacilities([]);
    setAnchorSelectedIndex(null);
    setAnchorManualName('');
  };

  const handleSaveAnchorName = async () => {
    if (!selectedAnchor) return;

    // In anchor-naming mode, we don't require routeNumber
    // Use the first route from the anchor's links, or allow global naming
    const anchorRouteNumber = routeNumber || null;

    const trimmedManual = anchorManualName.trim();
    let payload: AnchorNameUpsertRequest | null = null;

    if (trimmedManual.length > 0) {
      payload = {
        name: trimmedManual,
        source_type: 'manual',
        rutenummer: anchorRouteNumber || undefined, // Optional in anchor-naming mode
      };
    } else if (anchorSelectedIndex !== null) {
      const candidate = anchorCandidates[anchorSelectedIndex];
      if (candidate) {
        payload = {
          name: candidate.name,
          source_type: candidate.source_type,
          source_id: candidate.source_id,
          distance_meters: candidate.distance_meters ?? undefined,
          rutenummer: anchorRouteNumber || undefined, // Optional in anchor-naming mode
        };
      }
    }

    if (!payload) {
      notificationManager.warning('Velg et forslag eller skriv inn et navn');
      return;
    }

    try {
      const response = await api.upsertAnchorName(selectedAnchor.anchor_node_id, payload);
      setAnchorNodes((prev) =>
        prev.map((anchor) =>
          anchor.anchor_node_id === selectedAnchor.anchor_node_id
            ? {
                ...anchor,
                name: {
                  name: response.name,
                  source_type: response.source_type,
                  source_id: response.source_id,
                  distance_meters: response.distance_meters,
                  validated_by: response.validated_by,
                  validated_at: response.validated_at,
                },
              }
            : anchor
        )
      );

      // Invalidate route endpoint caches so tooltips will update with new anchor name
      // This affects both LinksLayer cache (routeInfoCacheRef) and MapView cache (routeEndpointsCacheRef)
      routeEndpointsCacheRef.current.clear();

      // Also invalidate route info cache in LinksLayer
      if (linksLayerCacheInvalidateRef.current) {
        linksLayerCacheInvalidateRef.current();
      }

      notificationManager.success('Ankernavn oppdatert');
      closeAnchorDialog();
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Update Anchor Name');
      notificationManager.error(`Kunne ikke oppdatere ankernavn: ${appError.message}`);
    }
  };

  const handleDrawComplete = async (geometry: GeoJSON.LineString) => {
    const tempId = `tmp_${crypto.randomUUID()}`;
    const event = {
      type: 'segment.add' as const,
      temp_id: tempId,
      geometry,
      srid: 4326,
      attrs: {},
    };

    try {
      if (changeset) {
        // Add to existing changeset
        await api.addEvent(changeset.id, event);
        onEventAdded(event);
        notificationManager.success('Segment lagt til');
      } else {
        // Add to localEvents (no changeset yet)
        onEventAdded(event);
        notificationManager.success('Segment lagt til (ulagret)');
      }
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Add Segment');
      notificationManager.error(`Kunne ikke legge til segment: ${appError.message}`);
    }
  };

  const handleEditComplete = async (layerId: string, geometry: GeoJSON.LineString) => {
    // Find if this is a base segment or new segment
    const event = {
      type: 'segment.update_geom' as const,
      target: { kind: 'segment' as const, id: layerId },
      geometry,
      srid: 4326,
    };

    try {
      if (changeset) {
        // Add to existing changeset
        await api.addEvent(changeset.id, event);
        onEventAdded(event);
        notificationManager.success('Geometri oppdatert');
      } else {
        // Add to localEvents (no changeset yet)
        onEventAdded(event);
        notificationManager.success('Geometri oppdatert (ulagret)');
      }
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Update Geometry');
      notificationManager.error(`Kunne ikke oppdatere geometri: ${appError.message}`);
    }
  };

  const handleSplitSegment = async (segmentId: string, splitPoint: number[], originalGeometry: GeoJSON.LineString, originalAttrs: Record<string, unknown>) => {
    try {
      const coords = originalGeometry.coordinates;
      if (!coords || coords.length < 2) {
        notificationManager.warning('Kan ikke dele segment uten gyldig geometri');
        return;
      }

      const isSamePoint = (a: number[], b: number[]) =>
        Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;

      if (isSamePoint(splitPoint, coords[0]) || isSamePoint(splitPoint, coords[coords.length - 1])) {
        notificationManager.warning('Deling må skje mellom endepunktene, ikke på endepunkt');
        return;
      }

      const [firstPart, secondPart] = splitLineStringAtPoint(originalGeometry, splitPoint);

      if (firstPart.coordinates.length < 2 || secondPart.coordinates.length < 2) {
        notificationManager.warning('Deling gir for korte segmenter');
        return;
      }

      const isNew = isNewSegment(segmentId);

      if (isNew) {
        // For new segments: delete the original and add two new ones
        const deleteEvent: SegmentDeleteNewEvent = {
          type: 'segment.delete_new',
          target: { kind: 'segment', temp_id: segmentId },
        };

        const tempId1 = `tmp_${crypto.randomUUID()}`;
        const tempId2 = `tmp_${crypto.randomUUID()}`;

        const addEvent1: SegmentAddEvent = {
          type: 'segment.add',
          temp_id: tempId1,
          geometry: firstPart,
          srid: 4326,
          attrs: originalAttrs,
        };

        const addEvent2: SegmentAddEvent = {
          type: 'segment.add',
          temp_id: tempId2,
          geometry: secondPart,
          srid: 4326,
          attrs: originalAttrs,
        };

        if (changeset) {
          await api.addEvent(changeset.id, deleteEvent);
          await api.addEvent(changeset.id, addEvent1);
          await api.addEvent(changeset.id, addEvent2);
        }
        onEventAdded(deleteEvent);
        onEventAdded(addEvent1);
        onEventAdded(addEvent2);

        notificationManager.success(changeset ? 'Segment delt i to nye segmenter' : 'Segment delt i to nye segmenter (ulagret)');
      } else {
        // For existing segments: retire the original and add two new ones
        const retireEvent: SegmentRetireEvent = {
          type: 'segment.retire',
          target: { kind: 'segment', id: segmentId },
        };

        const tempId1 = `tmp_${crypto.randomUUID()}`;
        const tempId2 = `tmp_${crypto.randomUUID()}`;

        const addEvent1: SegmentAddEvent = {
          type: 'segment.add',
          temp_id: tempId1,
          geometry: firstPart,
          srid: 4326,
          attrs: originalAttrs,
        };

        const addEvent2: SegmentAddEvent = {
          type: 'segment.add',
          temp_id: tempId2,
          geometry: secondPart,
          srid: 4326,
          attrs: originalAttrs,
        };

        if (changeset) {
          await api.addEvent(changeset.id, retireEvent);
          await api.addEvent(changeset.id, addEvent1);
          await api.addEvent(changeset.id, addEvent2);
        }
        onEventAdded(retireEvent);
        onEventAdded(addEvent1);
        onEventAdded(addEvent2);

        notificationManager.success(changeset ? 'Segment delt i to nye segmenter' : 'Segment delt i to nye segmenter (ulagret)');
      }

      setActiveTool(null);
      if (onFeatureSelect) {
        onFeatureSelect('', undefined);
      }
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Split Segment');
      notificationManager.error(`Kunne ikke dele segment: ${appError.message}`);
    }
  };

  const handleDeleteSegment = async (segmentId: string) => {
    const isNew = isNewSegment(segmentId);

    try {
      if (isNew) {
        const event: SegmentDeleteNewEvent = {
          type: 'segment.delete_new',
          target: { kind: 'segment', temp_id: segmentId },
        };
        if (changeset) {
          await api.addEvent(changeset.id, event);
        }
        onEventAdded(event);
        notificationManager.success(changeset ? 'Segment slettet' : 'Segment slettet (ulagret)');
      } else {
        const event: SegmentRetireEvent = {
          type: 'segment.retire',
          target: { kind: 'segment', id: segmentId },
        };
        if (changeset) {
          await api.addEvent(changeset.id, event);
        }
        onEventAdded(event);
        notificationManager.success(changeset ? 'Segment pensjonert' : 'Segment pensjonert (ulagret)');
      }

      setActiveTool(null);
      if (onFeatureSelect) {
        onFeatureSelect('', undefined);
      }
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Delete Segment');
      notificationManager.error(`Kunne ikke slette segment: ${appError.message}`);
    }
  };

  const handleRetireSegment = async (segmentId: string) => {
    if (isNewSegment(segmentId)) {
      notificationManager.warning('Nye segmenter kan ikke pensjoneres. Bruk slett i stedet.');
      return;
    }

    try {
      const event: SegmentRetireEvent = {
        type: 'segment.retire',
        target: { kind: 'segment', id: segmentId },
      };
      if (changeset) {
        await api.addEvent(changeset.id, event);
      }
      onEventAdded(event);
      notificationManager.success(changeset ? 'Segment pensjonert' : 'Segment pensjonert (ulagret)');

      setActiveTool(null);
      if (onFeatureSelect) {
        onFeatureSelect('', undefined);
      }
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Retire Segment');
      notificationManager.error(`Kunne ikke pensjonere segment: ${appError.message}`);
    }
  };

  const getStyle = (feature: GeoJSON.Feature, layer: L.Layer) => {
    const props = feature.properties as { op?: string; [key: string]: unknown } | null;
    const op = props?.op;
    if (op === 'add') {
      return { color: '#2ecc71', weight: 4, opacity: 0.8 };
    } else if (op === 'update') {
      return { color: '#3498db', weight: 4, opacity: 0.8 };
    } else if (op === 'retire') {
      return { color: '#e74c3c', weight: 3, opacity: 0.5, dashArray: '10, 5' };
    }
    return { color: '#95a5a6', weight: 2, opacity: 0.6 };
  };

  const onEachFeature = (feature: GeoJSON.Feature, layer: L.Layer) => {
    const props = feature.properties as { id?: string | number; objid?: number | string; temp_id?: string; [key: string]: unknown } | null;
    // Normalize feature ID - try multiple sources and ensure string format
    const featureId = feature.id
      ? String(feature.id)
      : props?.id
        ? String(props.id)
        : props?.objid
          ? String(props.objid)
          : props?.temp_id
            ? String(props.temp_id)
            : null;
    const isSelected = featureId && (selectedFeatureIds.has(featureId) || (selectedFeatureId && String(featureId) === String(selectedFeatureId)));

    if (isSelected) {
      (layer as L.Path).setStyle({ weight: 6, color: '#2196f3', opacity: 1.0 });
    }

    layer.on('click', (e: L.LeafletMouseEvent) => {
      // Handle split mode
      if (activeTool === 'split' && feature.geometry.type === 'LineString') {
        const latlng = e.latlng;
        const clickedPoint: number[] = [latlng.lng, latlng.lat]; // GeoJSON format [lng, lat]
        const originalGeometry = feature.geometry;
        const originalAttrs = (feature.properties as Record<string, unknown>) || {};

        const closestPoint = findClosestPointOnLine(clickedPoint, originalGeometry.coordinates);

        setConfirmDialog({
          isOpen: true,
          title: 'Del segment',
          message: `Vil du dele segmentet på dette punktet?\n\nKoordinater: ${closestPoint[1].toFixed(6)}, ${closestPoint[0].toFixed(6)}`,
          confirmLabel: 'Del',
          cancelLabel: 'Avbryt',
          variant: 'warning',
          onConfirm: () => {
            if (featureId) {
              handleSplitSegment(String(featureId), closestPoint, originalGeometry, originalAttrs);
            }
            setConfirmDialog(null);
          },
        });
        return;
      }

      // Property ownership mode: fetch ownership for selected geometry
      if (showOwnership && onGeometrySelectForOwnership && feature.geometry) {
        if (feature.geometry.type === 'LineString') {
          onGeometrySelectForOwnership(feature.geometry);
          // Fetch ownership data
          if (onOwnershipDataChange) {
            onOwnershipDataChange(null); // Clear previous data
            api.getGeometryOwners(feature.geometry)
              .then((data) => {
                if (onOwnershipDataChange) {
                  onOwnershipDataChange(data);
                }
              })
              .catch((error) => {
                const appError = handleApiError(error, 'Property Ownership');
                notificationManager.error(`Kunne ikke laste grunneierinformasjon: ${appError.message}`);
              });
          }
        }
        return;
      }

      // Normal selection
      if (onFeatureSelect && featureId) {
        // Pass feature properties (which contain segment attributes)
        const featureProps = feature.properties as Record<string, unknown> | null;
        const isMultiSelect = e.originalEvent.ctrlKey || e.originalEvent.metaKey;
        debugLog('Feature clicked (diff/effective layer):', { featureId, selectedFeatureId, isMultiSelect, props: featureProps });
        onFeatureSelect(featureId, featureProps || undefined, isMultiSelect);
      } else {
        console.warn('Feature click ignored (diff/effective layer) - missing featureId or onFeatureSelect', { featureId, hasHandler: !!onFeatureSelect });
      }
    });

    // Enable Geoman editing
    if (layer instanceof L.Polyline && mapRef.current?.pm) {
      const layerWithPm = layer as L.Polyline & { pm?: { enable: (options: { allowSelfIntersection: boolean }) => void } };
      if (layerWithPm.pm) {
        layerWithPm.pm.enable({ allowSelfIntersection: false });
      }
    }
  };

  return (
    <div className="map-view" style={{ position: 'relative', width: '100%', height: '100%' }}>
      <MapContainer
        center={[61.5, 8.5]}
        zoom={7}
        style={{ width: '100%', height: '100%' }}
      >
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="OpenStreetMap">
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='© OpenStreetMap contributors'
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Kartverket Topo4">
            <TileLayer
              url="https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
              attribution='© <a href="https://www.kartverket.no/">Kartverket</a>'
              maxZoom={19}
            />
          </LayersControl.BaseLayer>
          <LayersControl.Overlay checked={showLinks} name="Lenker">
            <LinksLayer
              linksData={linksData}
              linksLayerRef={linksLayerRef}
              selectedFeatureId={selectedFeatureId}
              selectedFeatureIds={selectedFeatureIds}
              onFeatureSelect={onFeatureSelect}
              showOwnership={showOwnership}
              onGeometrySelectForOwnership={onGeometrySelectForOwnership}
              onOwnershipDataChange={onOwnershipDataChange}
              selectedRouteNumber={selectedRouteNumber}
              onRouteSelect={onRouteSelect}
              onCacheInvalidateRef={linksLayerCacheInvalidateRef}
            />
          </LayersControl.Overlay>
          <LayersControl.Overlay checked={showSegments} name="Segmenter">
            <SegmentsLayer
              segmentsData={segmentsData}
              segmentsLayerRef={segmentsLayerRef}
              selectedFeatureId={selectedFeatureId}
              selectedFeatureIds={selectedFeatureIds}
              onFeatureSelect={onFeatureSelect}
              onSegmentHoverStart={handleSegmentHoverStart}
              onSegmentHoverMove={handleSegmentHoverMove}
              onSegmentHoverEnd={handleSegmentHoverEnd}
            />
          </LayersControl.Overlay>
          <LayersControl.Overlay checked={showAnchors} name="Ankerpunkter">
            <LayerGroup />
          </LayersControl.Overlay>
          <LayersControl.Overlay checked={showSigns} name="Skilt">
            <LayerGroup />
          </LayersControl.Overlay>
          <LayersControl.Overlay checked={showOwnership} name="Grunneier">
            <LayerGroup />
          </LayersControl.Overlay>
        </LayersControl>

        <SegmentsLinksLayerControl
          onSegmentsToggle={onShowSegmentsChange}
          onLinksToggle={onShowLinksChange}
        />
        <LinksLayerControl onToggle={onShowLinksChange} />
        <AnkerpunkterLayerControl onToggle={onShowAnchorsChange} />
        <SignsLayerControl onToggle={onShowSignsChange} />
        <GrunneierLayerControl onToggle={onShowOwnershipChange} />

        {/* Signs layer: outside Overlay so it always has map context and can add/remove its layer by showSigns */}
        <SignsLayer
          showSigns={showSigns}
          signsData={signsData}
          selectedSignDestinations={selectedSignDestinations}
          onSignDestinationSelect={onSignDestinationSelect}
          signsLayerRef={signsLayerRef}
        />

        <MapInitializer
          onMapReady={(map) => {
            debugLog('MapInitializer callback: setting mapRef and mapReady');
            mapRef.current = map;
            setMapReady(true);
          }}
        />

        {editMode && (
          <GeomanControl
            onDrawComplete={handleDrawComplete}
            onEditComplete={handleEditComplete}
          />
        )}

        {mapReady && mapRef.current && <SnapLayer map={mapRef.current} snapManager={snapManager} />}

        {/* Diff layer */}
        {diffLayer && !showEffective && changeset && (
          <ReactLeafletGeoJSON
            data={diffLayer}
            style={getStyle}
            onEachFeature={onEachFeature}
          />
        )}

        {/* Effective layer */}
        {effectiveLayer && showEffective && changeset && (
          <ReactLeafletGeoJSON
            data={effectiveLayer}
            style={{ color: '#3498db', weight: 3, opacity: 0.7 }}
            onEachFeature={onEachFeature}
          />
        )}

      </MapContainer>

      {/* Layer toggle - only show when changeset exists */}
      {changeset && (
        <div style={{
          position: 'absolute',
          top: 10,
          right: 10,
          zIndex: 1000,
          background: 'white',
          padding: '8px',
          borderRadius: '4px',
          boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
        }}>
          <label>
            <input
              type="checkbox"
              checked={showEffective}
              onChange={(e) => setShowEffective(e.target.checked)}
            />
            {' '}Show effective
          </label>
        </div>
      )}


      {/* Toolbar - show when route is selected: Edit button and tools */}
      {routeNumber && (
        <div style={{
          position: 'absolute',
          top: 80,
          left: 20,
          zIndex: 1000,
          background: 'white',
          borderRadius: '8px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          padding: '8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}>
          {/* Edit route toggle */}
          <button
            onClick={() => onEditModeChange(!editMode)}
              style={{
                padding: '12px',
                border: 'none',
                borderRadius: '6px',
                background: editMode ? '#e74c3c' : '#f8f9fa',
                color: editMode ? 'white' : '#333',
                cursor: 'pointer',
                fontSize: '16px',
                fontWeight: editMode ? 'bold' : 'normal',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.2s',
                minWidth: '48px',
                minHeight: '48px',
              }}
              title={editMode ? 'Deaktiver redigeringsverktøy' : 'Aktiver redigeringsverktøy'}
            >
              {editMode ? '✏️ Rediger På' : '✏️ Rediger Rute'}
            </button>

          {/* Divider */}
          {editMode && (
            <div style={{
              height: '1px',
              background: '#dee2e6',
              margin: '4px 0',
            }} />
          )}

          {/* Edit tools - only show when edit mode is active */}
          {editMode && (
            <>
              {/* Draw new segment */}
              <button
                onClick={() => {
              if (mapRef.current?.pm) {
                const isActive = activeTool === 'draw';
                if (isActive) {
                  mapRef.current.pm.disableDraw();
                  setActiveTool(null);
                } else {
                  mapRef.current.pm.toggleDraw('Line', {
                    continueDrawing: false,
                    finishOn: 'dblclick',
                  });
                  setActiveTool('draw');
                }
              }
                }}
                style={{
                  padding: '12px',
                  border: 'none',
                  borderRadius: '6px',
                  background: activeTool === 'draw' ? '#007bff' : '#f8f9fa',
                  color: activeTool === 'draw' ? 'white' : '#333',
                  cursor: 'pointer',
                  fontSize: '20px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                  minWidth: '48px',
                  minHeight: '48px',
                }}
                title="Tegn nytt segment"
              >
                ✏️
              </button>

              {/* Edit geometry */}
              <button
                onClick={() => {
              if (mapRef.current?.pm) {
                const isActive = activeTool === 'edit';
                if (isActive) {
                  mapRef.current.pm.disableGlobalEditMode();
                  setActiveTool(null);
                } else {
                  mapRef.current.pm.toggleGlobalEditMode();
                  setActiveTool('edit');
                }
              }
                }}
                style={{
                  padding: '12px',
                  border: 'none',
                  borderRadius: '6px',
                  background: activeTool === 'edit' ? '#007bff' : '#f8f9fa',
                  color: activeTool === 'edit' ? 'white' : '#333',
                  cursor: 'pointer',
                  fontSize: '20px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                  minWidth: '48px',
                  minHeight: '48px',
                }}
                title="Rediger geometri"
              >
                🔧
              </button>

              {/* Edit segment/route data */}
              <button
                onClick={() => {
              debugLog('Edit button clicked:', {
                selectedFeatureId,
                selectedFeatureIdsSize: selectedFeatureIds.size,
                selectedFeatureIdsArray: Array.from(selectedFeatureIds),
                routeNumber
              });

              if (selectedFeatureId || selectedFeatureIds.size > 0) {
                // One or more segments selected - open edit form in InfoPanel
                debugLog('Opening edit form for segment(s)');
                if (onOpenEditForm) {
                  onOpenEditForm();
                } else {
                  notificationManager.info(
                    selectedFeatureIds.size > 1
                      ? `Rediger metadata for ${selectedFeatureIds.size} segmenter: Åpner redigeringsform`
                      : 'Rediger metadata: Åpner redigeringsform'
                  );
                }
                setActiveTool('edit-data');
              } else if (routeNumber) {
                // Route selected but no segment - open route edit form in InfoPanel
                // Note: changeset is not required for route editing (can use localEvents)
                debugLog('Opening edit form for route');
                if (onOpenEditForm) {
                  onOpenEditForm();
                } else {
                  notificationManager.info('Rediger rute-metadata: Åpner redigeringsform');
                }
              } else {
                notificationManager.warning('Velg en rute eller et segment først for å redigere data');
              }
                }}
                style={{
                  padding: '12px',
                  border: 'none',
                  borderRadius: '6px',
                  background: activeTool === 'edit-data' ? '#6f42c1' : '#f8f9fa',
                  color: activeTool === 'edit-data' ? 'white' : '#333',
                  cursor: 'pointer',
                  fontSize: '20px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                  minWidth: '48px',
                  minHeight: '48px',
                }}
                title="Rediger segment/rutedata (rutenummer, rutenavn, etc.)"
              >
                📋
              </button>

              {/* Split segment */}
              <button
                onClick={() => {
              if (activeTool === 'split') {
                setActiveTool(null);
                notificationManager.info('Deling av segment avbrutt');
              } else {
                notificationManager.info('Del segment: Klikk på et punkt på segmentet for å dele det');
                setActiveTool('split');
              }
                }}
                style={{
                  padding: '12px',
                  border: 'none',
                  borderRadius: '6px',
                  background: activeTool === 'split' ? '#ffc107' : '#f8f9fa',
                  color: activeTool === 'split' ? 'white' : '#333',
                  cursor: 'pointer',
                  fontSize: '20px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                  minWidth: '48px',
                  minHeight: '48px',
                }}
                title="Del segment"
              >
                ✂️
              </button>

              {/* Delete segment */}
              <button
                onClick={() => {
              if (!selectedFeatureId) {
                notificationManager.warning('Velg et segment først for å slette det');
                return;
              }

              const isNew = isNewSegment(selectedFeatureId);
              setConfirmDialog({
                isOpen: true,
                title: isNew ? 'Slett segment' : 'Pensjoner segment',
                message: isNew
                  ? 'Er du sikker på at du vil slette dette segmentet? Dette kan ikke angres.'
                  : 'Er du sikker på at du vil pensjonere dette segmentet? Dette kan ikke angres.',
                confirmLabel: isNew ? 'Slett' : 'Pensjoner',
                cancelLabel: 'Avbryt',
                variant: 'danger',
                onConfirm: () => {
                  handleDeleteSegment(selectedFeatureId);
                  setConfirmDialog(null);
                },
              });
                }}
                style={{
                  padding: '12px',
                  border: 'none',
                  borderRadius: '6px',
                  background: activeTool === 'delete' ? '#dc3545' : '#f8f9fa',
                  color: activeTool === 'delete' ? 'white' : '#333',
                  cursor: 'pointer',
                  fontSize: '20px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                  minWidth: '48px',
                  minHeight: '48px',
                }}
                title="Slett segment"
              >
                🗑️
              </button>
            </>
          )}

          {/* Divider between edit tools and inspection tools */}

        </div>
      )}


      {/* Pending changes indicator */}
      {localEventsCount > 0 && (
        <div style={{
          position: 'absolute',
          top: 20,
          right: 20,
          zIndex: 1000,
          background: '#fff3cd',
          border: '2px solid #ffc107',
          borderRadius: '8px',
          padding: '12px 16px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          <span style={{ fontSize: '18px' }}>💾</span>
          <div>
            <div style={{ fontWeight: 'bold', fontSize: '14px' }}>
              {localEventsCount} ulagrede endringer
            </div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Klikk "Lagre endringer" i sidepanelet
            </div>
          </div>
        </div>
      )}

      {/* Confirmation dialog */}
      {confirmDialog && (
        <ConfirmDialog
          isOpen={confirmDialog.isOpen}
          title={confirmDialog.title}
          message={confirmDialog.message}
          confirmLabel={confirmDialog.confirmLabel}
          cancelLabel={confirmDialog.cancelLabel}
          variant={confirmDialog.variant}
          onConfirm={confirmDialog.onConfirm}
          onCancel={() => setConfirmDialog(null)}
        />
      )}

      <AnchorNameDialog
        isOpen={anchorDialogOpen}
        anchor={selectedAnchor}
        candidates={anchorCandidates}
        facilities={anchorFacilities}
        selectedIndex={anchorSelectedIndex}
        manualName={anchorManualName}
        onSelectCandidate={setAnchorSelectedIndex}
        onManualNameChange={setAnchorManualName}
        onSave={handleSaveAnchorName}
        onCancel={closeAnchorDialog}
      />

      {/* Split mode indicator */}
      {activeTool === 'split' && (
        <div style={{
          position: 'absolute',
          top: 160,
          left: 20,
          zIndex: 1000,
          background: '#fff3cd',
          border: '2px solid #ffc107',
          borderRadius: '8px',
          padding: '12px 16px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          <span style={{ fontSize: '18px' }}>✂️</span>
          <div>
            <div style={{ fontWeight: 'bold', fontSize: '14px' }}>
              Del segment-modus aktiv
            </div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Klikk på et segment for å dele det
            </div>
          </div>
        </div>
      )}

      {/* Multi-select indicator */}
      {selectedFeatureIds.size > 1 && (
        <div style={{
          position: 'absolute',
          top: activeTool === 'split' ? 240 : 160,
          left: 20,
          zIndex: 1000,
          background: '#e7f3ff',
          border: '2px solid #2196f3',
          borderRadius: '8px',
          padding: '12px 16px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          <span style={{ fontSize: '18px' }}>✓</span>
          <div>
            <div style={{ fontWeight: 'bold', fontSize: '14px' }}>
              {selectedFeatureIds.size} segmenter valgt
            </div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Hold Ctrl/Cmd og klikk for å velge flere. Klikk "Rediger segment/rutedata" for bulk-redigering.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
