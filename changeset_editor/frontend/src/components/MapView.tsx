/** Map view component with Leaflet and Geoman */
import { useEffect, useRef, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON as ReactLeafletGeoJSON, useMap } from 'react-leaflet';
import L from 'leaflet';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import type { Changeset, LocalEvent, RoutesResponse, RouteSegmentsResponse, RouteLinksResponse, RouteInfo } from '../types';
import type { GeoJSON } from 'geojson';
import { SnapManager } from '../utils/snap';
import { api } from '../api/client';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';
import 'leaflet/dist/leaflet.css';

// Load Geoman dynamically to avoid Vite resolution issues
// Import is done in GeomanControl component when needed

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
  onFeatureSelect?: (id: string) => void;
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
    console.log('MapInitializer: map is ready', map);
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
  onFeatureSelect,
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

  // Load routes within bounding box
  useEffect(() => {
    console.log('Routes useEffect triggered:', { mapReady, mapRef: !!mapRef.current });
    
    if (!mapRef.current || !mapReady) {
      console.log('Skipping routes load - map not ready');
      return;
    }

    const loadRoutesInView = () => {
      if (!mapRef.current) {
        console.log('mapRef.current is null in loadRoutesInView');
        return;
      }
      
      const bounds = mapRef.current.getBounds();
      const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
      
      console.log('Loading routes in bbox:', bbox);
      
      fetch(`/api/v1/routes?bbox=${bbox}&include_geometry=true&limit=500`)
        .then(res => {
          console.log('Routes API response status:', res.status);
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
          }
          return res.json();
        })
        .then((data: RoutesResponse) => {
          console.log('Routes API response:', data);
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
          console.log(`Loaded ${filteredFeatures.length} routes with geometry`);
          
          setRoutesInView({
            type: 'FeatureCollection',
            features: filteredFeatures,
          });
        })
        .catch(() => {
          // Don't show notification for background route loading - just log silently
          // Errors are logged by handleApiError
        });
    };

    // Load routes on map move/zoom
    mapRef.current.on('moveend', loadRoutesInView);
    mapRef.current.on('zoomend', loadRoutesInView);
    
    // Initial load with a small delay to ensure map is fully initialized
    setTimeout(() => {
      console.log('Initial routes load');
      loadRoutesInView();
    }, 500);

    return () => {
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
      return;
    }

    // Load segments
    fetch(`/api/v1/routes/${routeNumber}/segments?include_geometry=true`)
      .then(res => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        return res.json();
      })
      .then((data: RouteSegmentsResponse) => {
        console.log('Segments API response:', data);
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
        console.log(`Loaded ${filteredFeatures.length} segments with geometry (out of ${features.length} total)`);
        if (filteredFeatures.length === 0 && features.length > 0) {
          console.warn('No segments with geometry found. First segment:', data.segments?.[0]);
        }
        setSegmentsData({
          type: 'FeatureCollection',
          features: filteredFeatures,
        });
      })
      .catch(error => {
        const appError = handleApiError(error, 'Load Segments');
        notificationManager.warning(`Kunne ikke laste segmenter: ${appError.message}`);
      });

    // Load links
    fetch(`/api/v1/routes/${routeNumber}/links?include_geometry=true`)
      .then(res => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        return res.json();
      })
      .then((data: RouteLinksResponse) => {
        console.log('Links API response:', data);
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
        console.log(`Loaded ${filteredFeatures.length} links with geometry (out of ${features.length} total)`);
        if (filteredFeatures.length === 0 && features.length > 0) {
          console.warn('No links with geometry found. First link:', data.links?.[0]);
        }
        setLinksData({
          type: 'FeatureCollection',
          features: filteredFeatures,
        });
      })
      .catch(error => {
        const appError = handleApiError(error, 'Load Links');
        notificationManager.warning(`Kunne ikke laste lenker: ${appError.message}`);
      });
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

    console.log('Displaying segments:', segmentsData.features.length, 'features');
    const segmentsLayer = L.geoJSON(segmentsData, {
      style: {
        color: '#9b59b6',
        weight: 4,
        opacity: 0.8,
      },
      onEachFeature: (feature, layer) => {
        const props = feature.properties as { objid?: number | string; rutenummer?: string; rutenavn?: string | null; length_m?: number | null; [key: string]: unknown } | null;
        if (props) {
          layer.bindPopup(`
          <strong>Segment ${props.objid ?? 'N/A'}</strong><br>
          Rute: ${props.rutenummer || 'N/A'}<br>
          Navn: ${props.rutenavn || 'Uten navn'}<br>
          Lengde: ${typeof props.length_m === 'number' ? props.length_m.toFixed(2) : 'N/A'} m
        `);
        }
      },
    }).addTo(mapRef.current);

    segmentsLayerRef.current = segmentsLayer;
  }, [showSegments, segmentsData, mapReady]);

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

    console.log('Displaying links:', linksData.features.length, 'features');
    const linksLayer = L.geoJSON(linksData, {
      style: {
        color: '#16a085',
        weight: 3,
        opacity: 0.7,
        dashArray: '5, 5',
      },
      onEachFeature: (feature, layer) => {
        const props = feature.properties as { link_id?: number; a_node?: number | null; b_node?: number | null; length_m?: number | null; [key: string]: unknown } | null;
        if (props) {
          layer.bindPopup(`
          <strong>Link ${props.link_id ?? 'N/A'}</strong><br>
          A-node: ${props.a_node ?? 'N/A'}<br>
          B-node: ${props.b_node ?? 'N/A'}<br>
          Lengde: ${typeof props.length_m === 'number' ? props.length_m.toFixed(2) : 'N/A'} m
        `);
        }
      },
    }).addTo(mapRef.current);

    linksLayerRef.current = linksLayer;
  }, [showLinks, linksData, mapReady]);

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

    // Add endpoints from links
    if (showLinks && linksData) {
      linksData.features.forEach((feature) => {
        if (feature.geometry.type === 'LineString') {
          const coords = feature.geometry.coordinates;
          if (coords.length > 0) {
            // Start point
            const startKey = `${coords[0][0]},${coords[0][1]}`;
            if (!endpointSet.has(startKey)) {
              endpointSet.add(startKey);
              L.circleMarker([coords[0][1], coords[0][0]], {
                radius: 6,
                fillColor: '#16a085',
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
                fillColor: '#16a085',
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

    endpointsLayerRef.current = endpointsGroup;
  }, [showSegments, showLinks, segmentsData, linksData, mapReady]);

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

  const handleDrawComplete = async (geometry: GeoJSON.LineString) => {
    if (!changeset) return;
    
    const tempId = `tmp_${crypto.randomUUID()}`;
    const event = {
      type: 'segment.add' as const,
      temp_id: tempId,
      geometry,
      srid: 4326,
      attrs: {},
    };
    try {
      await api.addEvent(changeset.id, event);
      onEventAdded(event);
      notificationManager.success('Segment lagt til');
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Add Segment');
      notificationManager.error(`Kunne ikke legge til segment: ${appError.message}`);
    }
  };

  const handleEditComplete = async (layerId: string, geometry: GeoJSON.LineString) => {
    if (!changeset) return;
    
    // Find if this is a base segment or new segment
    const event = {
      type: 'segment.update_geom' as const,
      target: { kind: 'segment' as const, id: layerId },
      geometry,
      srid: 4326,
    };
    try {
      await api.addEvent(changeset.id, event);
      onEventAdded(event);
      notificationManager.success('Geometri oppdatert');
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Update Geometry');
      notificationManager.error(`Kunne ikke oppdatere geometri: ${appError.message}`);
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
    const props = feature.properties as { id?: string | number; [key: string]: unknown } | null;
    const featureId = feature.id || props?.id;
    const isSelected = String(featureId) === String(selectedFeatureId);

    if (isSelected) {
      (layer as L.Path).setStyle({ weight: 6, color: '#2196f3', opacity: 1.0 });
    }

    layer.on('click', () => {
      if (onFeatureSelect && featureId) {
        onFeatureSelect(String(featureId));
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
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <MapContainer
        center={[61.5, 8.5]}
        zoom={7}
        style={{ width: '100%', height: '100%' }}
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='© OpenStreetMap contributors'
        />
        
        <MapInitializer 
          onMapReady={(map) => {
            console.log('MapInitializer callback: setting mapRef and mapReady');
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
          top: 20,
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
              if (selectedFeatureId) {
                // TODO: Open dialog/panel to edit segment data
                notificationManager.info('Rediger segment/rutedata: Åpner dialog for å redigere rutenummer, rutenavn, etc.');
                setActiveTool('edit-data');
              } else {
                notificationManager.warning('Velg et segment først for å redigere data');
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
              // TODO: Implement split segment
              notificationManager.info('Del segment: Klikk på et punkt på segmentet for å dele det');
              setActiveTool('split');
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
              if (selectedFeatureId) {
                // TODO: Implement delete segment
                notificationManager.info('Slett segment: Segment vil bli slettet');
                setActiveTool('delete');
              } else {
                notificationManager.warning('Velg et segment først for å slette det');
              }
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
    </div>
  );
}
