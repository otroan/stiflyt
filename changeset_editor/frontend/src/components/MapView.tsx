/** Map view component with Leaflet and Geoman */
import { useEffect, useRef, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON as ReactLeafletGeoJSON, useMap, LayersControl } from 'react-leaflet';
import L from 'leaflet';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import type { Changeset, LocalEvent, RoutesResponse, RouteSegmentsResponse, RouteLinksResponse, RouteInfo, SegmentAddEvent, SegmentDeleteNewEvent, SegmentRetireEvent, AnchorNodeInfo, PlacenameCandidate, AnchorNameUpsertRequest, FacilityCandidate } from '../types';
import type { GeoJSON } from 'geojson';
import { SnapManager } from '../utils/snap';
import { api, isAbortError } from '../api/client';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';
import { findClosestPointOnLine, splitLineStringAtPoint, isNewSegment } from '../utils/geometry';
import { ConfirmDialog } from './ConfirmDialog';
import { AnchorNameDialog } from './AnchorNameDialog';
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
  onRouteSelect?: (rutenummer: string) => void;
  onEventAdded: (event: LocalEvent) => void;
  selectedFeatureId?: string;
  selectedFeatureIds?: Set<string>; // Multi-select support - all selected feature IDs
  onFeatureSelect?: (id: string, properties?: Record<string, unknown>, isMultiSelect?: boolean) => void;
  onOpenEditForm?: () => void; // Callback to open edit form in InfoPanel
  localEventsCount?: number;
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
  const [showSegments, setShowSegments] = useState(false);
  const [showLinks, setShowLinks] = useState(false);
  const [segmentsData, setSegmentsData] = useState<GeoJSON.FeatureCollection | null>(null);
  const [linksData, setLinksData] = useState<GeoJSON.FeatureCollection | null>(null);
  const segmentsLayerRef = useRef<L.GeoJSON | null>(null);
  const linksLayerRef = useRef<L.GeoJSON | null>(null);
  const endpointsLayerRef = useRef<L.LayerGroup | null>(null);
  const [anchorNodes, setAnchorNodes] = useState<AnchorNodeInfo[]>([]);
  const [anchorCandidates, setAnchorCandidates] = useState<PlacenameCandidate[]>([]);
  const [anchorFacilities, setAnchorFacilities] = useState<FacilityCandidate[]>([]);
  const [selectedAnchor, setSelectedAnchor] = useState<AnchorNodeInfo | null>(null);
  const [anchorDialogOpen, setAnchorDialogOpen] = useState(false);
  const [anchorSelectedIndex, setAnchorSelectedIndex] = useState<number | null>(null);
  const [anchorManualName, setAnchorManualName] = useState('');
  const [anchorSearchRadius] = useState(1500);

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

  // Load routes within bounding box
  useEffect(() => {
    debugLog('Routes useEffect triggered:', { mapReady, mapRef: !!mapRef.current });

    if (!mapRef.current || !mapReady) {
      debugLog('Skipping routes load - map not ready');
      return;
    }

    let requestId = 0;
    let activeController: AbortController | null = null;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    const loadRoutesInView = () => {
      if (!mapRef.current) {
        debugLog('mapRef.current is null in loadRoutesInView');
        return;
      }

      const bounds = mapRef.current.getBounds();
      const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

      debugLog('Loading routes in bbox:', bbox);

      requestId += 1;
      const currentRequestId = requestId;
      if (activeController) {
        activeController.abort();
      }
      activeController = new AbortController();

      api.getRoutesInBbox(bbox, { signal: activeController.signal })
        .then((data: RoutesResponse) => {
          if (currentRequestId !== requestId) {
            return;
          }
          debugLog('Routes API response:', data);
          // Convert routes to GeoJSON FeatureCollection
          // Convert routes to GeoJSON FeatureCollection
          // Note: RouteInfo doesn't have route_geometry, but RoutesResponse routes might
          const features: GeoJSON.Feature[] = (data.routes || [])
            .map((route) => {
              // Type assertion: routes from API may have route_geometry
              const routeWithGeometry = route as RouteInfo & { route_geometry?: GeoJSON.Geometry | null };
              const geometry = routeWithGeometry.route_geometry;
              if (!geometry) {
                return null;
              }
              return {
                type: 'Feature' as const,
                id: route.rutenummer,
                geometry: geometry,
                properties: {
                  rutenummer: route.rutenummer,
                  rutenavn: route.rutenavn,
                  vedlikeholdsansvarlig: route.vedlikeholdsansvarlig,
                },
              } as GeoJSON.Feature;
            })
            .filter((f): f is GeoJSON.Feature => f !== null);

          const filteredFeatures = features.filter((f) => f.geometry !== null && f.geometry !== undefined);
          debugLog(`Loaded ${filteredFeatures.length} routes with geometry`);

          setRoutesInView({
            type: 'FeatureCollection',
            features: filteredFeatures,
          });
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          // Don't show notification for background route loading - just log silently
          // Errors are logged by handleApiError
        });
    };

    // Load routes on map move/zoom
    mapRef.current.on('moveend', loadRoutesInView);
    mapRef.current.on('zoomend', loadRoutesInView);

    // Initial load with a small delay to ensure map is fully initialized
    timeoutId = setTimeout(() => {
      debugLog('Initial routes load');
      loadRoutesInView();
    }, 500);

    return () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      if (activeController) {
        activeController.abort();
      }
      if (mapRef.current) {
        mapRef.current.off('moveend', loadRoutesInView);
        mapRef.current.off('zoomend', loadRoutesInView);
      }
    };
  }, [mapReady]);


  // Load segments and links when route is selected
  useEffect(() => {
    if (!routeNumber || !mapReady) {
      setSegmentsData(null);
      setLinksData(null);
      setShowSegments(false);
      setShowLinks(false);
      setAnchorNodes([]);
      return;
    }

    // Reset toggles while loading new data
    setShowSegments(false);

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

    return () => {
      segmentsController.abort();
      linksController.abort();
    };
  }, [routeNumber, mapReady]);

  // Load anchor nodes for selected route
  useEffect(() => {
    if (!routeNumber || !mapReady) {
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
  }, [routeNumber, mapReady]);

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

  // Display segments
  useEffect(() => {
    if (!mapRef.current || !mapReady) {
      if (segmentsLayerRef.current && mapRef.current) {
        mapRef.current.removeLayer(segmentsLayerRef.current);
        segmentsLayerRef.current = null;
      }
      return;
    }

    // Remove layer if not showing or no data
    if (!showSegments || !segmentsData) {
      if (segmentsLayerRef.current) {
        mapRef.current.removeLayer(segmentsLayerRef.current);
        segmentsLayerRef.current = null;
      }
      return;
    }

    // Clear previous segments layer
    if (segmentsLayerRef.current) {
      mapRef.current.removeLayer(segmentsLayerRef.current);
      segmentsLayerRef.current = null;
    }

    debugLog('Displaying segments:', segmentsData.features.length, 'features');
    const segmentsLayer = L.geoJSON(segmentsData, {
      style: (feature) => {
        const props = feature?.properties as { objid?: number | string; segment_objid?: number | string; [key: string]: unknown } | null;
        // Normalize feature ID for style matching
        const featureId = feature?.id
          ? String(feature.id)
          : props?.objid
            ? String(props.objid)
            : props?.segment_objid
              ? String(props.segment_objid)
              : null;
        const isSelected = featureId && (selectedFeatureIds.has(featureId) || (selectedFeatureId && String(featureId) === String(selectedFeatureId)));
        return {
          color: isSelected ? '#2196f3' : '#9b59b6',
          weight: isSelected ? 6 : 4,
          opacity: isSelected ? 1.0 : 0.8,
        };
      },
      onEachFeature: (feature, layer) => {
        const props = feature.properties as { objid?: number | string; rutenummer?: string; rutenavn?: string | null; length_m?: number | null; [key: string]: unknown } | null;
        // Normalize feature ID - ensure it's a string and try multiple sources
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

        // Add click handler for selection
        layer.on('click', (e: L.LeafletMouseEvent) => {
          if (onFeatureSelect && featureId) {
            const featureProps = feature.properties as Record<string, unknown> | null;
            const isMultiSelect = e.originalEvent.ctrlKey || e.originalEvent.metaKey;
            debugLog('Segment clicked:', { featureId, selectedFeatureId, isMultiSelect, props: featureProps });
            onFeatureSelect(featureId, featureProps || undefined, isMultiSelect);
          } else {
            console.warn('Segment click ignored - missing featureId or onFeatureSelect', { featureId, hasHandler: !!onFeatureSelect });
          }
        });
      },
    }).addTo(mapRef.current);

    segmentsLayerRef.current = segmentsLayer;
  }, [showSegments, segmentsData, mapReady, selectedFeatureId, selectedFeatureIds, onFeatureSelect]);

  // Display links
  useEffect(() => {
    if (!mapRef.current || !mapReady) {
      if (linksLayerRef.current && mapRef.current) {
        mapRef.current.removeLayer(linksLayerRef.current);
        linksLayerRef.current = null;
      }
      return;
    }

    // Remove layer if not showing or no data
    if (!showLinks || !linksData) {
      if (linksLayerRef.current) {
        mapRef.current.removeLayer(linksLayerRef.current);
        linksLayerRef.current = null;
      }
      return;
    }

    // Clear previous links layer
    if (linksLayerRef.current) {
      mapRef.current.removeLayer(linksLayerRef.current);
      linksLayerRef.current = null;
    }

    debugLog('Displaying links:', linksData.features.length, 'features');
    const linksLayer = L.geoJSON(linksData, {
      style: (feature) => {
        const props = feature?.properties as { link_id?: number; [key: string]: unknown } | null;
        // Normalize feature ID for style matching
        const featureId = feature?.id
          ? String(feature.id)
          : props?.link_id
            ? String(props.link_id)
            : null;
        const isSelected = featureId && (selectedFeatureIds.has(featureId) || (selectedFeatureId && String(featureId) === String(selectedFeatureId)));
        return {
          color: isSelected ? '#2196f3' : '#16a085',
          weight: isSelected ? 5 : 4,
          opacity: isSelected ? 1.0 : 0.85,
          dashArray: '5, 5',
        };
      },
      onEachFeature: (feature, layer) => {
        const props = feature.properties as { link_id?: number; a_node?: number | null; b_node?: number | null; length_m?: number | null; [key: string]: unknown } | null;
        // Normalize feature ID - ensure it's a string
        const featureId = feature.id
          ? String(feature.id)
          : props?.link_id
            ? String(props.link_id)
            : null;

        if (props) {
          layer.bindPopup(`
          <strong>Link ${props.link_id ?? 'N/A'}</strong><br>
          A-node: ${props.a_node ?? 'N/A'}<br>
          B-node: ${props.b_node ?? 'N/A'}<br>
          Lengde: ${typeof props.length_m === 'number' ? props.length_m.toFixed(2) : 'N/A'} m
        `);
        }

        // Add click handler for selection
        layer.on('click', (e: L.LeafletMouseEvent) => {
          if (onFeatureSelect && featureId) {
            const featureProps = feature.properties as Record<string, unknown> | null;
            const isMultiSelect = e.originalEvent.ctrlKey || e.originalEvent.metaKey;
            debugLog('Link clicked:', { featureId, selectedFeatureId, isMultiSelect, props: featureProps });
            onFeatureSelect(featureId, featureProps || undefined, isMultiSelect);
          } else {
            console.warn('Link click ignored - missing featureId or onFeatureSelect', { featureId, hasHandler: !!onFeatureSelect });
          }
        });
      },
    }).addTo(mapRef.current);

    linksLayerRef.current = linksLayer;
  }, [showLinks, linksData, mapReady, selectedFeatureId, selectedFeatureIds, onFeatureSelect]);

  // Display endpoints (for segments and links)
  useEffect(() => {
    if (!mapRef.current || !mapReady) {
      if (endpointsLayerRef.current && mapRef.current) {
        mapRef.current.removeLayer(endpointsLayerRef.current);
        endpointsLayerRef.current = null;
      }
      return;
    }

    // Don't show endpoints if neither segments nor links are shown
    if (!showSegments && !showLinks) {
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

    // Add endpoints and midpoints from links
    if (showLinks && linksData) {
      linksData.features.forEach((feature) => {
        const addLinkMarkers = (coords: number[][]) => {
          if (coords.length === 0) return;

          // Start point
          const startKey = `${coords[0][0]},${coords[0][1]}`;
          linkEndpointCounts.set(startKey, (linkEndpointCounts.get(startKey) ?? 0) + 1);
          linkEndpointCoords.set(startKey, coords[0]);
          if (!linkEndpointSet.has(startKey)) {
            linkEndpointSet.add(startKey);
            L.circleMarker([coords[0][1], coords[0][0]], {
              radius: 8,
              fillColor: '#f39c12',
              color: '#2c3e50',
              weight: 2,
              opacity: 1,
              fillOpacity: 0.95,
              pane: 'link-endpoints',
            }).addTo(endpointsGroup);
          }

          // End point
          const endKey = `${coords[coords.length - 1][0]},${coords[coords.length - 1][1]}`;
          linkEndpointCounts.set(endKey, (linkEndpointCounts.get(endKey) ?? 0) + 1);
          linkEndpointCoords.set(endKey, coords[coords.length - 1]);
          if (!linkEndpointSet.has(endKey)) {
            linkEndpointSet.add(endKey);
            L.circleMarker([coords[coords.length - 1][1], coords[coords.length - 1][0]], {
              radius: 8,
              fillColor: '#f39c12',
              color: '#2c3e50',
              weight: 2,
              opacity: 1,
              fillOpacity: 0.95,
              pane: 'link-endpoints',
            }).addTo(endpointsGroup);
          }

          const midIndex = Math.floor(coords.length / 2);
          const midCoord = coords[midIndex];
          if (midCoord) {
            const midpointMarker = L.circleMarker([midCoord[1], midCoord[0]], {
              radius: 5,
              fillColor: '#ffffff',
              color: '#16a085',
              weight: 2,
              opacity: 1,
              fillOpacity: 0.9,
              pane: 'link-endpoints',
            }).addTo(endpointsGroup);
            const props = feature.properties as { link_id?: number | string; length_m?: number | null } | null;
            const lengthStr = typeof props?.length_m === 'number' ? `${props.length_m.toFixed(1)} m` : 'N/A';
            midpointMarker.bindTooltip(`Link ${props?.link_id ?? ''} • ${lengthStr}`, {
              permanent: true,
              direction: 'top',
              className: 'link-midpoint-label',
              opacity: 0.9,
            });
          }
        };

        if (feature.geometry.type === 'LineString') {
          addLinkMarkers(feature.geometry.coordinates);
        } else if (feature.geometry.type === 'MultiLineString') {
          feature.geometry.coordinates.forEach((line) => addLinkMarkers(line));
        }
      });
    }

    // Add anchor node markers (clickable for naming)
    if (showLinks && anchorNodes.length > 0) {
      anchorNodes.forEach((anchor) => {
        const [lon, lat] = anchor.coordinates;
        const nameLabel = anchor.name?.name || `Anchor ${anchor.anchor_node_id}`;
        const marker = L.circleMarker([lat, lon], {
          radius: 9,
          fillColor: '#2563eb',
          color: '#ffffff',
          weight: 2,
          opacity: 1,
          fillOpacity: 0.9,
          pane: 'link-endpoints',
        }).addTo(endpointsGroup);
        marker.bindTooltip(nameLabel, {
          permanent: false,
          direction: 'top',
          className: 'link-midpoint-label',
          opacity: 0.9,
        });
        marker.on('click', () => openAnchorDialog(anchor));
      });
    }

    // Highlight junctions where multiple links meet
    linkEndpointCounts.forEach((count, key) => {
      if (count > 1) {
        const coord = linkEndpointCoords.get(key);
        if (!coord) return;
        L.circleMarker([coord[1], coord[0]], {
          radius: 10,
          fillColor: '#e74c3c',
          color: '#ffffff',
          weight: 3,
          opacity: 1,
          fillOpacity: 0.95,
          pane: 'link-endpoints',
        }).addTo(endpointsGroup);
      }
    });

    endpointsLayerRef.current = endpointsGroup;
  }, [showSegments, showLinks, segmentsData, linksData, mapReady, anchorNodes]);

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

  const openAnchorDialog = (anchor: AnchorNodeInfo) => {
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
  };

  const closeAnchorDialog = () => {
    setAnchorDialogOpen(false);
    setSelectedAnchor(null);
    setAnchorCandidates([]);
    setAnchorFacilities([]);
    setAnchorSelectedIndex(null);
    setAnchorManualName('');
  };

  const handleSaveAnchorName = async () => {
    if (!selectedAnchor || !routeNumber) return;

    const trimmedManual = anchorManualName.trim();
    let payload: AnchorNameUpsertRequest | null = null;

    if (trimmedManual.length > 0) {
      payload = {
        name: trimmedManual,
        source_type: 'manual',
        rutenummer: routeNumber,
      };
    } else if (anchorSelectedIndex !== null) {
      const candidate = anchorCandidates[anchorSelectedIndex];
      if (candidate) {
        payload = {
          name: candidate.name,
          source_type: candidate.source_type,
          source_id: candidate.source_id,
          distance_meters: candidate.distance_meters ?? undefined,
          rutenummer: routeNumber,
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
        </LayersControl>

        <MapInitializer
          onMapReady={(map) => {
            debugLog('MapInitializer callback: setting mapRef and mapReady');
            mapRef.current = map;
            setMapReady(true);
          }}
        />

        <GeomanControl
          onDrawComplete={handleDrawComplete}
          onEditComplete={handleEditComplete}
        />

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

        {/* Routes in view - using React Leaflet GeoJSON for better integration */}
        {routesInView && (
          <ReactLeafletGeoJSON
            data={routesInView}
            style={(feature) => {
              const props = feature?.properties as { rutenummer?: string; [key: string]: unknown } | null;
              const rutenummer = props?.rutenummer;
              const isSelected = rutenummer === selectedRouteNumber;
              return {
                color: isSelected ? '#e74c3c' : '#3498db',
                weight: isSelected ? 6 : 3,
                opacity: isSelected ? 1.0 : 0.6,
              };
            }}
            onEachFeature={(feature, layer) => {
              const props = feature.properties as { rutenummer?: string; rutenavn?: string; [key: string]: unknown } | null;
              const rutenummer = props?.rutenummer;

              // Add popup
              layer.bindPopup(`
                <strong>${rutenummer}</strong><br>
                ${props?.rutenavn || 'Uten navn'}<br>
                ${props?.vedlikeholdsansvarlig || ''}
              `);

              // Make clickable
              layer.on('click', () => {
                if (onRouteSelect && rutenummer) {
                  onRouteSelect(rutenummer);
                }
              });

              // Change cursor on hover
              layer.on('mouseover', () => {
                layer.setStyle({ weight: 5 });
              });
              layer.on('mouseout', () => {
                const isSelected = rutenummer === selectedRouteNumber;
                layer.setStyle({
                  weight: isSelected ? 6 : 3,
                  color: isSelected ? '#e74c3c' : '#3498db',
                });
              });
            }}
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

      {/* Toolbar - show when route is selected */}
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

          {/* Divider */}
          <div style={{
            height: '1px',
            background: '#dee2e6',
            margin: '4px 0',
          }} />

          {/* Toggle segments */}
          <button
            onClick={() => setShowSegments(!showSegments)}
            style={{
              padding: '12px',
              border: 'none',
              borderRadius: '6px',
              background: showSegments ? '#9b59b6' : '#f8f9fa',
              color: showSegments ? 'white' : '#333',
              cursor: 'pointer',
              fontSize: '20px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.2s',
              minWidth: '48px',
              minHeight: '48px',
            }}
            title="Vis/skjul segmenter"
          >
            📍
          </button>

          {/* Toggle links */}
          <button
            onClick={() => setShowLinks(!showLinks)}
            style={{
              padding: '12px',
              border: 'none',
              borderRadius: '6px',
              background: showLinks ? '#16a085' : '#f8f9fa',
              color: showLinks ? 'white' : '#333',
              cursor: 'pointer',
              fontSize: '20px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.2s',
              minWidth: '48px',
              minHeight: '48px',
            }}
            title="Vis/skjul linker"
          >
            🔗
          </button>

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
