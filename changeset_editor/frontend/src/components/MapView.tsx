/** Map view component with Leaflet and Geoman */
import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MapContainer, TileLayer, GeoJSON as ReactLeafletGeoJSON, useMap, LayersControl, LayerGroup } from 'react-leaflet';
import L from 'leaflet';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import type { Changeset, LocalEvent, RoutesResponse, RouteSegmentsResponse, RouteLinksResponse, RouteInfo, SegmentAddEvent, SegmentDeleteNewEvent, SegmentRetireEvent, AnchorNodeInfo, PlacenameCandidate, AnchorNameUpsertRequest, FacilityCandidate, SignsReportResponse } from '../types';
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

type AppMode = 'inspection' | 'edit' | 'anchor-naming' | 'signs' | 'property-ownership';

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
  onSignDestinationSelect?: (destKey: string, selected: boolean) => void; // Callback for destination selection
  selectedSignDestinations?: Set<string>; // Selected destination keys
  activeMode: AppMode;
  onModeChange: (mode: AppMode) => void;
  selectedGeometryForOwnership?: GeoJSON.Geometry | null;
  onGeometrySelectForOwnership?: (geometry: GeoJSON.Geometry | null) => void;
  ownershipData?: any;
  onOwnershipDataChange?: (data: any) => void;
}

// Component to render the segments layer for LayersControl
function SegmentsLayer({
  segmentsData,
  segmentsLayerRef,
  selectedFeatureId,
  selectedFeatureIds,
  onFeatureSelect
}: {
  segmentsData: GeoJSON.FeatureCollection | null;
  segmentsLayerRef: React.MutableRefObject<L.GeoJSON | null>;
  selectedFeatureId?: string;
  selectedFeatureIds?: Set<string>;
  onFeatureSelect?: (id: string, properties?: Record<string, unknown>, isMultiSelect?: boolean) => void;
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
  activeMode,
  onGeometrySelectForOwnership,
  onOwnershipDataChange
}: {
  linksData: GeoJSON.FeatureCollection | null;
  linksLayerRef: React.MutableRefObject<L.GeoJSON | null>;
  selectedFeatureId?: string;
  selectedFeatureIds?: Set<string>;
  onFeatureSelect?: (id: string, properties?: Record<string, unknown>, isMultiSelect?: boolean) => void;
  activeMode?: AppMode;
  onGeometrySelectForOwnership?: (geometry: GeoJSON.Geometry | null) => void;
  onOwnershipDataChange?: (data: any) => void;
}) {
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const map = useMap();

  // Initialize layer group
  useEffect(() => {
    if (!layerGroupRef.current) {
      layerGroupRef.current = L.layerGroup();
    }
  }, []);

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
        const props = feature?.properties as { link_id?: number; [key: string]: unknown } | null;
        const featureId = feature?.id
          ? String(feature.id)
          : props?.link_id
            ? String(props.link_id)
            : null;
        const isSelected = featureId && (selectedFeatureIds?.has(featureId) || (selectedFeatureId && String(featureId) === String(selectedFeatureId)));
        return {
          color: isSelected ? '#2196f3' : '#16a085',
          weight: isSelected ? 5 : 4,
          opacity: isSelected ? 1.0 : 0.85,
          dashArray: '5, 5',
        };
      },
      onEachFeature: (feature, layer) => {
        const props = feature.properties as { link_id?: number; a_node?: number | null; b_node?: number | null; length_m?: number | null; [key: string]: unknown } | null;
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

        layer.on('click', (e: L.LeafletMouseEvent) => {
          // Property ownership mode: fetch ownership for link geometry
          if (activeMode === 'property-ownership' && onGeometrySelectForOwnership && feature.geometry) {
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
  }, [linksData, selectedFeatureId, selectedFeatureIds, onFeatureSelect, linksLayerRef, activeMode, onGeometrySelectForOwnership, onOwnershipDataChange]);

  return <LayerGroup ref={layerGroupRef} />;
}

// Component to render the signs layer for LayersControl
function SignsLayer({
  signsData,
  selectedSignDestinations,
  onSignDestinationSelect,
  signsLayerRef
}: {
  signsData: SignsReportResponse | null;
  selectedSignDestinations: Set<string>;
  onSignDestinationSelect?: (destKey: string, selected: boolean) => void;
  signsLayerRef: React.MutableRefObject<L.LayerGroup | null>;
}) {
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const map = useMap();

  // Initialize layer group and sync with signsLayerRef
  useEffect(() => {
    if (!layerGroupRef.current) {
      layerGroupRef.current = L.layerGroup();
      signsLayerRef.current = layerGroupRef.current;
    }
  }, [signsLayerRef]);

  // Create markers when signs data changes
  useEffect(() => {
    if (!layerGroupRef.current || !signsData) {
      return;
    }

    // Clear existing markers
    layerGroupRef.current.clearLayers();

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
      layerGroupRef.current?.addLayer(marker);

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
  }, [signsData, selectedSignDestinations, onSignDestinationSelect]);

  return <LayerGroup ref={layerGroupRef} />;
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
      } else if (e.name === 'Ankere') {
        onLinksToggle(true);
        // Deactivate segments when links are activated
        onSegmentsToggle(false);
      }
    };

    const handleOverlayRemove = (e: L.LayersControlEvent) => {
      if (e.name === 'Segmenter') {
        onSegmentsToggle(false);
      } else if (e.name === 'Ankere') {
        onLinksToggle(false);
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

// Custom Leaflet Control for Mode Selection
function ModeControl({
  activeMode,
  onModeChange,
  onEditModeChange
}: {
  activeMode: AppMode;
  onModeChange: (mode: AppMode) => void;
  onEditModeChange: (enabled: boolean) => void;
}) {
  const map = useMap();
  const controlRef = useRef<L.Control | null>(null);
  const [container, setContainer] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    // Create custom Leaflet control
    const ModeControlClass = L.Control.extend({
      onAdd: () => {
        const containerDiv = L.DomUtil.create('div', 'leaflet-bar leaflet-control leaflet-control-mode');
        containerDiv.style.background = 'white';
        containerDiv.style.borderRadius = '4px';
        containerDiv.style.boxShadow = '0 1px 5px rgba(0,0,0,0.4)';
        containerDiv.style.padding = '4px';
        containerDiv.style.marginTop = '10px'; // Space below zoom controls

        // Prevent map panning when clicking on control
        L.DomEvent.disableClickPropagation(containerDiv);
        L.DomEvent.disableScrollPropagation(containerDiv);

        setContainer(containerDiv);
        return containerDiv;
      },
      onRemove: () => {
        setContainer(null);
      }
    });

    // Create and add control to map
    controlRef.current = new ModeControlClass({ position: 'topright' });
    controlRef.current.addTo(map);

    return () => {
      if (controlRef.current) {
        map.removeControl(controlRef.current);
        controlRef.current = null;
      }
      setContainer(null);
    };
  }, [map]);

  // Render mode buttons using portal
  const modeLabels: Record<AppMode, string> = {
    'inspection': '👁️ Inspiser',
    'edit': '✏️ Rediger',
    'anchor-naming': '🏷️ Navngi Ankere',
    'signs': '🚩 Skilt',
    'property-ownership': '🏠 Grunneier',
  };

  const modes: AppMode[] = ['inspection', 'edit', 'anchor-naming', 'signs', 'property-ownership'];

  if (!container) {
    return null;
  }

  return createPortal(
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '4px',
    }}>
      <div style={{
        fontSize: '11px',
        fontWeight: 'bold',
        marginBottom: '2px',
        color: '#666',
        padding: '0 4px',
        textAlign: 'center',
      }}>
        Modus:
      </div>
      {modes.map((mode) => {
        const isActive = activeMode === mode;
        return (
          <button
            key={mode}
            onClick={() => {
              onModeChange(mode);
              // Auto-enable edit mode when entering edit mode
              if (mode === 'edit') {
                onEditModeChange(true);
              } else {
                onEditModeChange(false);
              }
            }}
            style={{
              padding: '6px 10px',
              border: 'none',
              borderRadius: '4px',
              background: isActive ? '#007bff' : '#f8f9fa',
              color: isActive ? 'white' : '#333',
              cursor: 'pointer',
              fontSize: '12px',
              fontWeight: isActive ? 'bold' : 'normal',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.2s',
              whiteSpace: 'nowrap',
              width: '100%',
            }}
            title={modeLabels[mode]}
          >
            {modeLabels[mode]}
          </button>
        );
      })}
    </div>,
    container
  );
}

// Component to handle layer control changes
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
  onSignDestinationSelect,
  selectedSignDestinations = new Set(),
  activeMode,
  onModeChange,
  selectedGeometryForOwnership,
  onGeometrySelectForOwnership,
  ownershipData,
  onOwnershipDataChange,
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
  const [showSegments, setShowSegments] = useState(true); // Default: segments selected
  const [showLinks, setShowLinks] = useState(false); // Default: links not selected (mutually exclusive with segments)
  const [showSigns, setShowSigns] = useState(false);
  const [editMode, setEditMode] = useState(false); // Separate edit mode toggle
  const [segmentsData, setSegmentsData] = useState<GeoJSON.FeatureCollection | null>(null);
  const [linksData, setLinksData] = useState<GeoJSON.FeatureCollection | null>(null);
  const [signsData, setSignsData] = useState<SignsReportResponse | null>(null);
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
    let debounceTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let initialLoadTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let lastBbox: string | null = null;
    const DEBOUNCE_DELAY = 300; // ms - delay before making API call after map movement stops

    const loadRoutesInView = async () => {
      if (!mapRef.current) {
        debugLog('mapRef.current is null in loadRoutesInView');
        return;
      }

      const bounds = mapRef.current.getBounds();
      const zoom = mapRef.current.getZoom();
      const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

      // Request deduplication: skip if bbox hasn't changed
      if (bbox === lastBbox) {
        debugLog('Skipping duplicate bbox request:', bbox);
        return;
      }
      lastBbox = bbox;

      // Calculate bbox area for logging
      const bboxWidth = bounds.getEast() - bounds.getWest();
      const bboxHeight = bounds.getNorth() - bounds.getSouth();
      const bboxArea = bboxWidth * bboxHeight;

      debugLog('Loading routes in bbox:', { bbox, zoom, bboxArea: bboxArea.toFixed(6) });

      requestId += 1;
      const currentRequestId = requestId;
      
      // Abort any pending request
      if (activeController) {
        activeController.abort();
        activeController = null;
      }
      activeController = new AbortController();

      try {
        // Load routes with max limit 1000 (API maximum)
        // If there are more routes, user should zoom in to reduce bbox size
        const limit = 1000;
        const data = await api.getRoutesInBbox(bbox, { signal: activeController.signal });

        // Ignore response if it's outdated (newer request was made)
        if (currentRequestId !== requestId) {
          debugLog('Ignoring outdated response for request', currentRequestId);
          return;
        }

        const totalRoutes = data.total ?? 0;
        const returnedRoutes = data.routes?.length || 0;

        debugLog('Routes API response:', {
          total: totalRoutes,
          limit: limit,
          returned: returnedRoutes,
          zoom,
          bboxArea: bboxArea.toFixed(6)
        });

        // Warn if not all routes are loaded - user should zoom in
        if (totalRoutes > limit) {
          console.warn(
            `Not all routes are displayed: ${totalRoutes} total routes in view, but only ${limit} loaded. ` +
            `Zoom in to see more routes in the smaller area.`
          );
        }

        // Convert routes to GeoJSON FeatureCollection
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
        debugLog(`Loaded ${filteredFeatures.length} routes with geometry (out of ${totalRoutes} total, zoom: ${zoom}, bbox area: ${bboxArea.toFixed(6)})`);

        setRoutesInView({
          type: 'FeatureCollection',
          features: filteredFeatures,
        });
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

    // Load routes on map move/zoom (with debouncing)
    mapRef.current.on('moveend', debouncedLoadRoutes);
    mapRef.current.on('zoomend', debouncedLoadRoutes);

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
  }, [mapReady]);


  // Load segments and links - by route if selected, otherwise by bbox in inspection mode
  useEffect(() => {
    if (!mapReady) {
      return;
    }

    // In edit mode, require route selection
    if (activeMode === 'edit' && !routeNumber) {
      setSegmentsData(null);
      setLinksData(null);
      setShowSegments(false);
      setShowLinks(false);
      setAnchorNodes([]);
      return;
    }

    // In inspection mode, load by bbox if no route selected
    if (activeMode === 'inspection' && !routeNumber && mapRef.current) {
      const bounds = mapRef.current.getBounds();
      const bbox = {
        xmin: bounds.getWest(),
        ymin: bounds.getSouth(),
        xmax: bounds.getEast(),
        ymax: bounds.getNorth(),
      };

      const linksController = new AbortController();

      // Load links by bbox
      api.getLinksByBbox(bbox, 500, { signal: linksController.signal })
        .then((data: GeoJSON.FeatureCollection) => {
          debugLog('Links by bbox API response:', data);
          setLinksData(data);
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          const appError = handleApiError(error, 'Load Links');
          notificationManager.warning(`Kunne ikke laste linker: ${appError.message}`);
        });

      // Note: Segments don't have a bbox endpoint yet, so we skip them when no route is selected
      setSegmentsData(null);
      // Don't clear anchor nodes here - they're loaded separately by bbox in inspection mode

      return () => {
        linksController.abort();
      };
    }

    // Load anchors by bbox in anchor-naming mode
    if (activeMode === 'anchor-naming' && mapRef.current && !routeNumber) {
      const bounds = mapRef.current.getBounds();
      const bbox = {
        xmin: bounds.getWest(),
        ymin: bounds.getSouth(),
        xmax: bounds.getEast(),
        ymax: bounds.getNorth(),
      };

      const anchorsController = new AbortController();

      api.getAnchorsByBbox(bbox, 500, { signal: anchorsController.signal })
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
              link_count: 0, // Not available from bbox endpoint
            };
          });
          setAnchorNodes(anchors);
        })
        .catch((error) => {
          if (isAbortError(error)) return;
          // Silently fail - anchors are optional
        });

      return () => {
        anchorsController.abort();
      };
    }

    // Don't clear anchors in inspection mode - they should always be loaded
    // Only clear when switching away from inspection/anchor-naming modes
    if (activeMode !== 'anchor-naming' && activeMode !== 'inspection') {
      setAnchorNodes([]);
    }

    // Load by route if route is selected
    if (!routeNumber) {
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

    // Load anchor nodes for the route (always in inspection and anchor-naming modes)
    if (activeMode === 'anchor-naming' || activeMode === 'inspection') {
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
  }, [routeNumber, mapReady, activeMode]);

  // Reload links by bbox when map moves/zooms in inspection mode without route
  useEffect(() => {
    if (!mapReady || !mapRef.current || activeMode !== 'inspection' || routeNumber) {
      return; // Only reload on map changes if in inspection mode without route
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

      api.getLinksByBbox(bbox, 500, { signal: activeController.signal })
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
  }, [mapReady, activeMode, routeNumber]);

  // Reload anchors by bbox when map moves/zooms in inspection or anchor-naming mode
  useEffect(() => {
    if (!mapReady || !mapRef.current || (activeMode !== 'anchor-naming' && activeMode !== 'inspection') || routeNumber) {
      return; // Only reload on map changes if in inspection or anchor-naming mode without route
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
  }, [mapReady, activeMode, routeNumber]);

  // Load anchor nodes for selected route
  // Only load when route is selected - in inspection mode without route, anchors are loaded by bbox
  useEffect(() => {
    if (!routeNumber || !mapReady) {
      // Only clear anchors if not in inspection mode (inspection mode loads by bbox)
      if (activeMode !== 'inspection' && activeMode !== 'anchor-naming') {
        setAnchorNodes([]);
      }
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
  }, [routeNumber, mapReady, activeMode]);

  // Load signs data when layer is enabled - based on map viewport or route/prefix
  // In signs mode, always load by viewport
  useEffect(() => {
    if (!showSigns || !mapReady || !mapRef.current) {
      setSignsData(null);
      return;
    }

    const controller = new AbortController();

    // Priority: route > prefix > bbox (map viewport)
    // In signs mode, prefer bbox unless route/prefix is explicitly provided
    let loadPromise: Promise<SignsReportResponse | null> = Promise.resolve(null);

    if (routeNumber && activeMode !== 'signs') {
      // Load by route if available (unless in signs mode)
      loadPromise = api.getRouteSigns(routeNumber, { signal: controller.signal });
    } else if (signsPrefix && signsPrefix.trim().length >= 2 && activeMode !== 'signs') {
      // Load by prefix if provided (unless in signs mode)
      loadPromise = api.getSignsByPrefix(signsPrefix.trim(), { signal: controller.signal });
    } else {
      // Load by map viewport (bbox) - default for signs mode
      const bounds = mapRef.current.getBounds();
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
  }, [showSigns, mapReady, routeNumber, signsPrefix, activeMode]);

  // Reload signs when map moves/zooms (if using bbox mode or in signs mode)
  useEffect(() => {
    if (!showSigns || !mapReady || !mapRef.current) {
      return;
    }

    // In signs mode, always use bbox. Otherwise, only if no route/prefix
    const shouldUseBbox = activeMode === 'signs' || (!routeNumber && (!signsPrefix || signsPrefix.trim().length < 2));
    if (!shouldUseBbox) {
      return;
    }

    let timeoutId: ReturnType<typeof setTimeout>;
    let activeController: AbortController | null = null;

    const loadSignsInView = () => {
      if (activeController) {
        activeController.abort();
      }
      activeController = new AbortController();

      const bounds = mapRef.current?.getBounds();
      if (!bounds) return;

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
        });
    };

    mapRef.current.on('moveend', loadSignsInView);
    mapRef.current.on('zoomend', loadSignsInView);

    // Initial load with a small delay
    timeoutId = setTimeout(() => {
      loadSignsInView();
    }, 300);

    return () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      if (activeController) {
        activeController.abort();
      }
      if (mapRef.current) {
        mapRef.current.off('moveend', loadSignsInView);
        mapRef.current.off('zoomend', loadSignsInView);
      }
    };
  }, [showSigns, mapReady, routeNumber, signsPrefix, activeMode]);

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

    // Always show endpoints layer in inspection mode (for anchor markers)
    // In other modes, only show if segments or links are shown
    if (activeMode !== 'inspection' && !showSegments && !showLinks) {
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
    if (anchorNodes.length > 0) {
      anchorNodes.forEach((anchor) => {
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

    // Add endpoints and midpoints from links
    if (showLinks && linksData) {
      linksData.features.forEach((feature) => {
        const addLinkMarkers = (coords: number[][]) => {
          if (coords.length === 0) return;

          // Start point
          const startLon = coords[0][0];
          const startLat = coords[0][1];
          const startKey = `${startLon},${startLat}`;
          linkEndpointCounts.set(startKey, (linkEndpointCounts.get(startKey) ?? 0) + 1);
          linkEndpointCoords.set(startKey, coords[0]);

          // Check if this coordinate is an anchor - if so, skip creating duplicate marker
          const startAnchor = findAnchorAtCoord(startLon, startLat);
          if (!linkEndpointSet.has(startKey) && !startAnchor) {
            linkEndpointSet.add(startKey);
            const marker = L.circleMarker([startLat, startLon], {
              radius: 8,
              fillColor: '#f39c12',
              color: '#2c3e50',
              weight: 2,
              opacity: 1,
              fillOpacity: 0.95,
              pane: 'link-endpoints',
            }).addTo(endpointsGroup);
            // Add click handler if this is an anchor (shouldn't happen due to check above, but just in case)
            if (startAnchor) {
              marker.on('click', () => openAnchorDialog(startAnchor));
            }
          }

          // End point
          const endLon = coords[coords.length - 1][0];
          const endLat = coords[coords.length - 1][1];
          const endKey = `${endLon},${endLat}`;
          linkEndpointCounts.set(endKey, (linkEndpointCounts.get(endKey) ?? 0) + 1);
          linkEndpointCoords.set(endKey, coords[coords.length - 1]);

          // Check if this coordinate is an anchor - if so, skip creating duplicate marker
          const endAnchor = findAnchorAtCoord(endLon, endLat);
          if (!linkEndpointSet.has(endKey) && !endAnchor) {
            linkEndpointSet.add(endKey);
            const marker = L.circleMarker([endLat, endLon], {
              radius: 8,
              fillColor: '#f39c12',
              color: '#2c3e50',
              weight: 2,
              opacity: 1,
              fillOpacity: 0.95,
              pane: 'link-endpoints',
            }).addTo(endpointsGroup);
            // Add click handler if this is an anchor (shouldn't happen due to check above, but just in case)
            if (endAnchor) {
              marker.on('click', () => openAnchorDialog(endAnchor));
            }
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

    // Add anchor node markers (always show in inspection and anchor-naming modes)
    // Use smaller markers when links are not shown, larger when links are shown
    if ((activeMode === 'anchor-naming' || activeMode === 'inspection') && anchorNodes.length > 0) {
      anchorNodes.forEach((anchor) => {
        const [lon, lat] = anchor.coordinates;
        const nameLabel = anchor.name?.name || `Anchor ${anchor.anchor_node_id}`;
        const hasName = !!anchor.name?.name;

        // Determine marker size and style based on mode and link visibility
        const isSmallMarker = activeMode === 'inspection' && !showLinks;
        const marker = L.circleMarker([lat, lon], {
          radius: activeMode === 'anchor-naming'
            ? 10
            : isSmallMarker
              ? 6  // Small marker when links are hidden
              : 9, // Normal size when links are shown
          fillColor: activeMode === 'anchor-naming'
            ? (hasName ? '#16a085' : '#e74c3c')
            : isSmallMarker
              ? '#6b7280'  // Gray for small markers
              : '#2563eb', // Blue for normal markers
          color: '#ffffff',
          weight: activeMode === 'anchor-naming' ? 3 : (isSmallMarker ? 1.5 : 2),
          opacity: 1,
          fillOpacity: isSmallMarker ? 0.8 : 0.9,
          pane: 'link-endpoints',
        }).addTo(endpointsGroup);

        // Tooltip shows on hover (permanent: false) with anchor name
        marker.bindTooltip(
          activeMode === 'anchor-naming' && !hasName
            ? `${nameLabel} (mangler navn)`
            : nameLabel,
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

    // Highlight junctions where multiple links meet
    // Skip creating junction markers if there's already an anchor marker at that location
    linkEndpointCounts.forEach((count, key) => {
      if (count > 1) {
        const coord = linkEndpointCoords.get(key);
        if (!coord) return;
        const [lon, lat] = coord;

        // Check if this coordinate is an anchor - if so, skip creating duplicate marker
        const anchor = findAnchorAtCoord(lon, lat);
        if (!anchor) {
          // Only create junction marker if there's no anchor at this location
          L.circleMarker([lat, lon], {
            radius: 10,
            fillColor: '#e74c3c',
            color: '#ffffff',
            weight: 3,
            opacity: 1,
            fillOpacity: 0.95,
            pane: 'link-endpoints',
          }).addTo(endpointsGroup);
        }
      }
    });

    endpointsLayerRef.current = endpointsGroup;
    // Note: openAnchorDialog is intentionally not in dependencies as it's stable (uses stable state setters and constant anchorSearchRadius)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showSegments, showLinks, segmentsData, linksData, mapReady, anchorNodes, activeMode]);

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
      if (activeMode === 'property-ownership' && onGeometrySelectForOwnership && feature.geometry) {
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
          <LayersControl.Overlay checked={showSegments} name="Segmenter">
            <SegmentsLayer
              segmentsData={segmentsData}
              segmentsLayerRef={segmentsLayerRef}
              selectedFeatureId={selectedFeatureId}
              selectedFeatureIds={selectedFeatureIds}
              onFeatureSelect={onFeatureSelect}
            />
          </LayersControl.Overlay>
          <LayersControl.Overlay checked={showLinks} name="Ankere">
            <LinksLayer
              linksData={linksData}
              linksLayerRef={linksLayerRef}
              selectedFeatureId={selectedFeatureId}
              selectedFeatureIds={selectedFeatureIds}
              onFeatureSelect={onFeatureSelect}
              activeMode={activeMode}
              onGeometrySelectForOwnership={onGeometrySelectForOwnership}
              onOwnershipDataChange={onOwnershipDataChange}
            />
          </LayersControl.Overlay>
          <LayersControl.Overlay checked={showSigns} name="Skilt">
            <SignsLayer
              signsData={signsData}
              selectedSignDestinations={selectedSignDestinations}
              onSignDestinationSelect={onSignDestinationSelect}
              signsLayerRef={signsLayerRef}
            />
          </LayersControl.Overlay>
        </LayersControl>

        <SegmentsLinksLayerControl
          onSegmentsToggle={setShowSegments}
          onLinksToggle={setShowLinks}
        />
        <SignsLayerControl onToggle={setShowSigns} />

        <ModeControl
          activeMode={activeMode}
          onModeChange={onModeChange}
          onEditModeChange={setEditMode}
        />

        <MapInitializer
          onMapReady={(map) => {
            debugLog('MapInitializer callback: setting mapRef and mapReady');
            mapRef.current = map;
            setMapReady(true);
          }}
        />

        {activeMode === 'edit' && editMode && (
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

        {/* Routes in view - using React Leaflet GeoJSON for better integration */}
        {routesInView && (
          <ReactLeafletGeoJSON
            key={`routes-${routesInView.features.length}-${routesInView.features[0]?.id || 'empty'}`}
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

              // Make clickable - toggle selection if already selected
              layer.on('click', () => {
                if (onRouteSelect && rutenummer) {
                  // If this route is already selected, deselect it; otherwise select it
                  if (rutenummer === selectedRouteNumber) {
                    onRouteSelect(null);
                  } else {
                    onRouteSelect(rutenummer);
                  }
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


      {/* Toolbar - show when route is selected or in edit mode */}
      {(routeNumber || activeMode === 'edit') && (
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
          {/* Edit Mode Toggle - only in edit mode */}
          {activeMode === 'edit' && (
            <button
              onClick={() => setEditMode(!editMode)}
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
              {editMode ? '🔧 Verktøy På' : '🔧 Verktøy Av'}
            </button>
          )}

          {/* Divider */}
          {editMode && (
            <div style={{
              height: '1px',
              background: '#dee2e6',
              margin: '4px 0',
            }} />
          )}

          {/* Edit tools - only show in edit mode and when edit mode is active */}
          {activeMode === 'edit' && editMode && (
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
