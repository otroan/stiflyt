/**
 * Route viewer functionality - displays routes with property information
 */

class RouteViewer {
    constructor(map, layerControl, options = {}) {
        this.map = map;
        this.layerControl = layerControl;
        this.currentRouteData = null;
        this.routeLayer = null;
        this.routeLayerGroup = null;
        this.propertyLayers = [];
        this.propertyLayerGroup = null;
        this.segmentLayerGroup = null;
        this.markers = [];
        this.autoZoom = options.autoZoom !== false; // Default to true, can be disabled
        this.showSegments = options.showSegments === true; // Default to false, must be explicitly enabled
        this.showComponents = options.showComponents === true; // Default to false, must be explicitly enabled

        // Bounding box route layers
        this.bboxRouteLayerGroup = null;
        this.bboxRoutes = new Map(); // Map of rutenummer -> layer for quick lookup
        this.routeDataMap = new Map(); // Map of rutenummer -> route data for overlapping route selector
        this.routeSelectorPopup = null; // Current route selector popup

        // Color palette for properties (from constants)
        this.colors = PROPERTY_COLORS;

        // Track loading state to prevent race conditions
        this._currentLoadId = null;
        this._isLoading = false;

        // Debounce timer for bounding box queries
        this._bboxQueryTimer = null;
        this._bboxQueryDelay = 100; // 100ms delay for responsive updates

        // Flag to prevent bbox reloading when a specific route is being loaded
        this._loadingSpecificRoute = false;

        // Store last bbox filters to allow reloading after route load
        this._lastBboxFilters = null;
    }

    /**
     * Clear all route-related layers from the map
     * Properly disposes of layers and removes event listeners to prevent memory leaks
     */
    clear() {
        // Close any open popups before removing layers
        this.map.closePopup();

        // Remove route layer
        if (this.routeLayer) {
            // Clear any popups on the layer
            if (this.routeLayer.closePopup) {
                this.routeLayer.closePopup();
            }
            // Remove all event listeners and remove from map
            this.routeLayer.off();
            this.map.removeLayer(this.routeLayer);
            this.routeLayer = null;
        }

        // Remove route layer group (for disconnected components)
        if (this.routeLayerGroup) {
            // Clear all layers in the group first
            this.routeLayerGroup.eachLayer(layer => {
                if (layer.closePopup) {
                    layer.closePopup();
                }
                layer.off();
            });
            this.routeLayerGroup.clearLayers();
            this.layerControl.removeLayer(this.routeLayerGroup);
            this.map.removeLayer(this.routeLayerGroup);
            this.routeLayerGroup = null;
        }

        // Remove property layers
        this.propertyLayers.forEach(layer => {
            if (layer.closePopup) {
                layer.closePopup();
            }
            layer.off();
            this.map.removeLayer(layer);
        });
        this.propertyLayers = [];

        if (this.propertyLayerGroup) {
            // Clear all layers in the group first
            this.propertyLayerGroup.eachLayer(layer => {
                if (layer.closePopup) {
                    layer.closePopup();
                }
                layer.off();
            });
            this.propertyLayerGroup.clearLayers();
            this.layerControl.removeLayer(this.propertyLayerGroup);
            this.map.removeLayer(this.propertyLayerGroup);
            this.propertyLayerGroup = null;
        }

        // Remove segment layer
        if (this.segmentLayerGroup) {
            // Clear all layers in the group first
            this.segmentLayerGroup.eachLayer(layer => {
                if (layer.closePopup) {
                    layer.closePopup();
                }
                layer.off();
            });
            this.segmentLayerGroup.clearLayers();
            this.layerControl.removeLayer(this.segmentLayerGroup);
            this.map.removeLayer(this.segmentLayerGroup);
            this.segmentLayerGroup = null;
        }

        // Remove markers
        this.markers.forEach(marker => {
            if (marker.closePopup) {
                marker.closePopup();
            }
            marker.off();
            this.map.removeLayer(marker);
        });
        this.markers = [];

        // Don't clear bounding box routes here - they should remain visible
        // Only clear the specific route's bbox layer if it exists
        if (this.currentRouteData && this.currentRouteData.metadata) {
            const currentRutenummer = this.currentRouteData.metadata.rutenummer;
            if (this.bboxRoutes.has(currentRutenummer)) {
                const bboxLayer = this.bboxRoutes.get(currentRutenummer);
                if (bboxLayer && this.bboxRouteLayerGroup) {
                    this.bboxRouteLayerGroup.removeLayer(bboxLayer);
                    this.bboxRoutes.delete(currentRutenummer);
                }
            }
        }

        this.currentRouteData = null;
    }

    /**
     * Clear bounding box route layers
     */
    clearBboxRoutes() {
        if (this.bboxRouteLayerGroup) {
            this.bboxRouteLayerGroup.eachLayer(layer => {
                if (layer.closePopup) {
                    layer.closePopup();
                }
                layer.off();
            });
            this.bboxRouteLayerGroup.clearLayers();
        }
        this.bboxRoutes.clear();
        this.routeDataMap.clear();

        // Close route selector if open
        if (this.routeSelectorPopup) {
            this.map.removeLayer(this.routeSelectorPopup);
            this.routeSelectorPopup = null;
        }
    }

    /**
     * Load and display routes within the current map bounding box
     * @param {Object} filters - Optional filters {prefix, organization}
     */
    async loadRoutesInBbox(filters = {}) {
        // Don't reload bbox routes if a specific route is currently being loaded
        // But allow reloading after the route has finished loading
        if (this._isLoading && this._loadingSpecificRoute) {
            console.log('Skipping bbox route reload - specific route is currently loading');
            return;
        }

        // Clear any pending queries
        if (this._bboxQueryTimer) {
            clearTimeout(this._bboxQueryTimer);
            this._bboxQueryTimer = null;
        }

        // Get current map bounds and zoom level
        const bounds = this.map.getBounds();
        const zoom = this.map.getZoom();
        const bbox = {
            min_lat: bounds.getSouth(),
            min_lng: bounds.getWest(),
            max_lat: bounds.getNorth(),
            max_lng: bounds.getEast()
        };

        try {
            // Load routes in bounding box with zoom level for adaptive simplification
            const data = await loadRoutesInBbox(bbox, { ...filters, limit: 1000, zoom: zoom });

            // Get currently loaded route rutenummer to exclude it from bbox routes
            const currentRutenummer = this.currentRouteData?.metadata?.rutenummer;

            // Clear previous bounding box routes (but keep the layer group)
            this.clearBboxRoutes();

            // Create layer group if it doesn't exist
            if (!this.bboxRouteLayerGroup) {
                this.bboxRouteLayerGroup = L.layerGroup().addTo(this.map);
                this.layerControl.addOverlay(this.bboxRouteLayerGroup, 'Ruter i visning');
            }

            // Batch create layers for better performance
            // Use requestAnimationFrame to avoid blocking UI
            const routesToAdd = data.routes.filter(route => {
                if (!route.geometry) {
                    return false; // Skip routes without geometry
                }
                // Skip the currently loaded route - it's already displayed with full details
                if (route.rutenummer === currentRutenummer) {
                    return false;
                }
                return true;
            });

            // Create layers in batches to avoid blocking
            const batchSize = 20;
            let batchIndex = 0;

            const processBatch = () => {
                const endIndex = Math.min(batchIndex + batchSize, routesToAdd.length);

                for (let i = batchIndex; i < endIndex; i++) {
                    const route = routesToAdd[i];

                    // Use backend-provided distance - backend always provides total_length_km
                    // Don't calculate from geometry as it only shows visible/simplified part
                    const distanceKm = route.total_length_km ?? 0;
                    const distanceDisplay = distanceKm > 0 ? `${distanceKm.toFixed(2)} km` : 'N/A';

                    // Add popup with route info (lazy - only create when needed)
                    const popupContent = `
                        <div style="min-width: 200px;">
                            <strong>${route.rutenummer}</strong><br>
                            ${route.rutenavn || 'Ingen navn'}<br>
                            <small>
                                ${route.vedlikeholdsansvarlig || 'Ukjent organisasjon'}<br>
                                ${route.segment_count} segment(er)
                            </small><br>
                            <em style="font-size: 0.85em; color: #6c757d;">Klikk for å laste full rute</em>
                        </div>
                    `;

                    // Tooltip content for hover
                    const tooltipContent = `
                        <div style="font-weight: 600;">
                            ${route.rutenummer}<br>
                            <small style="font-weight: normal;">${distanceDisplay}</small>
                        </div>
                    `;

                    // Create GeoJSON layer for this route with optimized styling
                    const routeLayer = createGeoJSONLayer(route.geometry, {
                        style: {
                            color: '#3498db', // Blue for overview routes
                            weight: 2,
                            opacity: 0.6,
                            fillOpacity: 0
                        },
                        popupContent: popupContent,
                        tooltipContent: tooltipContent, // Bind tooltips via onEachFeature
                        layerName: `route-${route.rutenummer}`
                    });

                    // Set lower z-index so selected routes appear on top
                    if (routeLayer && routeLayer.setZIndex) {
                        routeLayer.setZIndex(100); // Lower z-index for bbox routes
                    }

                        // Store route data for overlapping route selector
                        this.routeDataMap.set(route.rutenummer, route);

                        // Add click handler with support for overlapping routes
                        if (routeLayer) {
                            // Bind click to individual layers to detect overlaps
                            setTimeout(() => {
                                if (routeLayer.eachLayer) {
                                    routeLayer.eachLayer((layer) => {
                                        layer.on('click', (e) => {
                                            L.DomEvent.stopPropagation(e);
                                            this.handleRouteClick(e, route.rutenummer);
                                        });
                                    });
                                } else {
                                    routeLayer.on('click', (e) => {
                                        L.DomEvent.stopPropagation(e);
                                        this.handleRouteClick(e, route.rutenummer);
                                    });
                                }
                            }, 50);

                        // Add hover effects and bind tooltips to individual layers after adding to map
                        // Tooltips must be bound AFTER layer is on map to work properly
                        setTimeout(() => {
                            if (routeLayer.eachLayer) {
                                routeLayer.eachLayer(function(layer) {
                                    // Store original weight for restoration
                                    const originalWeight = layer.options.weight || 2;

                                    // Bind tooltip if pending (stored during layer creation)
                                    if (layer._pendingTooltipContent && layer.bindTooltip) {
                                        try {
                                            layer.bindTooltip(layer._pendingTooltipContent, {
                                                permanent: false,
                                                direction: 'auto',
                                                className: 'route-tooltip',
                                                opacity: 0.95,
                                                offset: [0, -5]
                                            });

                                            // Manually open/close tooltip on hover
                                            layer.on('mouseover', function(e) {
                                                if (this.openTooltip) {
                                                    this.openTooltip(e.latlng);
                                                }
                                            });
                                            layer.on('mouseout', function(e) {
                                                if (this.closeTooltip) {
                                                    this.closeTooltip();
                                                }
                                            });

                                            delete layer._pendingTooltipContent;
                                        } catch (error) {
                                            console.error('Error binding tooltip to layer:', error);
                                        }
                                    }

                                    // Bind hover effect to make route thicker
                                    layer.on('mouseover', function(e) {
                                        this.setStyle({ weight: originalWeight * 2.5 });
                                    });
                                    layer.on('mouseout', function(e) {
                                        this.setStyle({ weight: originalWeight });
                                    });
                                });
                            } else {
                                // Single layer
                                const originalWeight = routeLayer.options.weight || 2;

                                // Bind tooltip if pending
                                if (routeLayer._pendingTooltipContent && routeLayer.bindTooltip) {
                                    try {
                                        routeLayer.bindTooltip(routeLayer._pendingTooltipContent, {
                                            permanent: false,
                                            direction: 'auto',
                                            className: 'route-tooltip',
                                            opacity: 0.95,
                                            offset: [0, -5]
                                        });

                                        routeLayer.on('mouseover', function(e) {
                                            if (this.openTooltip) {
                                                this.openTooltip(e.latlng);
                                            }
                                        });
                                        routeLayer.on('mouseout', function(e) {
                                            if (this.closeTooltip) {
                                                this.closeTooltip();
                                            }
                                        });

                                        delete routeLayer._pendingTooltipContent;
                                    } catch (error) {
                                        console.error('Error binding tooltip to single layer:', error);
                                    }
                                }

                                routeLayer.on('mouseover', function(e) {
                                    this.setStyle({ weight: originalWeight * 2.5 });
                                });
                                routeLayer.on('mouseout', function(e) {
                                    this.setStyle({ weight: originalWeight });
                                });
                            }
                        }, 50);

                        // Add to layer group and store reference
                        routeLayer.addTo(this.bboxRouteLayerGroup);

                        this.bboxRoutes.set(route.rutenummer, routeLayer);
                    }
                }

                batchIndex = endIndex;

                // Process next batch if there are more routes
                if (batchIndex < routesToAdd.length) {
                    requestAnimationFrame(processBatch);
                }
            };

            // Start processing batches
            if (routesToAdd.length > 0) {
                processBatch();
            }

            console.log(`Loaded ${data.routes.length} routes in bounding box`);

        } catch (error) {
            console.error('Error loading routes in bounding box:', error);
            // Don't show alert for bbox queries to avoid spam
        }
    }

    /**
     * Debounced version of loadRoutesInBbox
     * Waits for map to stop moving before querying
     * @param {Object} filters - Optional filters {prefix, organization}
     */
    loadRoutesInBboxDebounced(filters = {}) {
        // Store filters for potential reload after route load
        this._lastBboxFilters = filters;

        // Clear existing timer
        if (this._bboxQueryTimer) {
            clearTimeout(this._bboxQueryTimer);
        }

        // Set new timer
        this._bboxQueryTimer = setTimeout(() => {
            this.loadRoutesInBbox(filters);
            this._bboxQueryTimer = null;
        }, this._bboxQueryDelay);
    }

    /**
     * Load and display a route
     * @param {string} rutenummer - Route identifier
     */
    async loadRoute(rutenummer) {
        console.log('RouteViewer.loadRoute called with rutenummer:', rutenummer);

        if (!rutenummer) {
            throw new Error('Vennligst skriv inn et rutenummer');
        }

        // Generate unique load ID for this request
        const loadId = Date.now() + Math.random();
        this._currentLoadId = loadId;
        this._isLoading = true;
        this._loadingSpecificRoute = true; // Prevent bbox routes from reloading

        try {
            // Clear previous route synchronously before starting async operations
            // This ensures clean state before new data loads
            this.clear();

            // Remove this route from bbox routes if it exists
            if (this.bboxRoutes.has(rutenummer)) {
                const bboxLayer = this.bboxRoutes.get(rutenummer);
                if (bboxLayer && this.bboxRouteLayerGroup) {
                    this.bboxRouteLayerGroup.removeLayer(bboxLayer);
                    this.bboxRoutes.delete(rutenummer);
                }
            }

            // Load route data
            const data = await loadRouteData(rutenummer);

            // Check if this load was cancelled by a newer load request
            if (this._currentLoadId !== loadId) {
                console.log('RouteViewer.loadRoute: Load cancelled by newer request');
                return null;
            }

            this.currentRouteData = data;

            // Display route geometry
            // If route has multiple components, display each as a separate layer (only if showComponents is enabled)
            if (data.geometry) {
                if (this.showComponents && data.components && data.components.length > 1) {
                    // Multiple disconnected components - display each separately
                    this.routeLayerGroup = L.layerGroup();

                    // Use different colors for each component (from constants)
                    const colors = COMPONENT_COLORS;

                    data.components.forEach((component, index) => {
                        // Extract geometry for this component from the MultiLineString
                        // The MultiLineString coordinates array contains one LineString per component
                        let componentGeometry = null;

                        if (data.geometry && data.geometry.type === 'MultiLineString' && data.geometry.coordinates) {
                            // Extract the LineString(s) for this component
                            // Each component corresponds to one or more LineStrings in the MultiLineString
                            // We need to map component index to the correct LineString(s)

                            // For now, if components are in order, use index to get the corresponding LineString
                            // This assumes the backend returns components in the same order as MultiLineString coordinates
                            if (index < data.geometry.coordinates.length) {
                                const componentCoords = data.geometry.coordinates[index];
                                if (componentCoords && componentCoords.length > 0) {
                                    componentGeometry = {
                                        type: 'LineString',
                                        coordinates: componentCoords
                                    };
                                }
                            }
                        }

                        // Fallback: if we can't extract from MultiLineString, try building from matrikkelenhet_vector
                        if (!componentGeometry && data.matrikkelenhet_vector) {
                            const componentSegments = data.matrikkelenhet_vector.filter(item =>
                                component.includes(item.segment_objid || -1)
                            );

                            const componentGeometries = componentSegments
                                .filter(item => item.geometry && item.geometry.coordinates)
                                .map(item => item.geometry);

                            if (componentGeometries.length > 0) {
                                if (componentGeometries.length === 1) {
                                    componentGeometry = componentGeometries[0];
                                } else {
                                    // Combine multiple geometries
                                    const allCoordinates = componentGeometries
                                        .map(geom => {
                                            if (geom.type === 'LineString') {
                                                return [geom.coordinates];
                                            } else if (geom.type === 'MultiLineString') {
                                                return geom.coordinates;
                                            }
                                            return null;
                                        })
                                        .filter(coords => coords !== null)
                                        .flat();

                                    if (allCoordinates.length > 0) {
                                        componentGeometry = {
                                            type: 'MultiLineString',
                                            coordinates: allCoordinates
                                        };
                                    }
                                }
                            }
                        }

                        if (!componentGeometry) {
                            console.warn(`Component ${index + 1} has no valid geometry`);
                            return; // Skip this component
                        }

                        const componentColor = colors[index % colors.length];

                        // Create tooltip content if metadata available
                        let tooltipContent = null;
                        if (data.metadata) {
                            const rutenummer = data.metadata.rutenummer;
                            const distanceKm = data.metadata.total_length_km || 0;
                            tooltipContent = `
                                <div style="font-weight: 600;">
                                    ${rutenummer}<br>
                                    <small style="font-weight: normal;">${distanceKm.toFixed(2)} km</small>
                                </div>
                            `;
                        }

                        // Create a layer for this component with filtered geometry
                        const popupContent = `
                            <strong>Komponent ${index + 1}</strong><br>
                            Segmenter: ${component.length}<br>
                            ${data.metadata?.component_count ? `Totalt ${data.metadata.component_count} komponenter` : ''}
                        `;
                        const componentLayer = createGeoJSONLayer(componentGeometry, {
                            style: {
                                color: componentColor,
                                weight: 4,
                                opacity: 0.8
                            },
                            popupContent: popupContent,
                            tooltipContent: tooltipContent,
                            layerGroup: this.routeLayerGroup,
                            layerName: `component-${index + 1}`
                        });
                        if (!componentLayer) {
                            console.warn(`Failed to create layer for component ${index + 1}`);
                        }
                    });

                    this.routeLayerGroup.addTo(this.map);
                    this.layerControl.addOverlay(this.routeLayerGroup, `Rute (${data.components.length} komponenter)`);

                    // Ensure selected route components appear on top of bbox routes
                    this.routeLayerGroup.eachLayer(layer => {
                        if (layer.bringToFront) {
                            layer.bringToFront();
                        }
                        if (layer.setZIndex) {
                            layer.setZIndex(1000); // Higher than bbox routes (100)
                        }
                    });

                    // Fit map to all components (only if autoZoom is enabled)
                    if (this.autoZoom && this.routeLayerGroup.getLayers().length > 0) {
                        const bounds = getBoundsFromLayer(this.routeLayerGroup, 'routeLayerGroup');
                        if (bounds) {
                            fitMapToBounds(this.map, bounds);
                        }
                    }
                } else {
                    // Single connected route
                    // Create tooltip content if metadata available
                    let tooltipContent = null;
                    if (data.metadata) {
                        const rutenummer = data.metadata.rutenummer;
                        const distanceKm = data.metadata.total_length_km || 0;
                        tooltipContent = `
                            <div style="font-weight: 600;">
                                ${rutenummer}<br>
                                <small style="font-weight: normal;">${distanceKm.toFixed(2)} km</small>
                            </div>
                        `;
                    }

                    // Use createGeoJSONLayer to ensure tooltips work properly
                    this.routeLayer = createGeoJSONLayer(data.geometry, {
                        style: {
                            color: '#2c3e50',
                            weight: 5,
                            opacity: 0.8
                        },
                        tooltipContent: tooltipContent,
                        layerName: 'selected-route'
                    });

                    if (this.routeLayer) {
                        this.routeLayer.addTo(this.map);
                    }

                    // Ensure selected route appears on top of bbox routes
                    if (this.routeLayer) {
                        if (this.routeLayer.bringToFront) {
                            this.routeLayer.bringToFront();
                        }
                        // Set higher z-index for selected route
                        if (this.routeLayer.setZIndex) {
                            this.routeLayer.setZIndex(1000); // Higher than bbox routes (100)
                        }
                        // Also ensure all sub-layers have high z-index
                        if (this.routeLayer.eachLayer) {
                            this.routeLayer.eachLayer(layer => {
                                if (layer.bringToFront) {
                                    layer.bringToFront();
                                }
                                if (layer.setZIndex) {
                                    layer.setZIndex(1000);
                                }
                            });
                        }
                    }

                    // Fit map to route bounds (only if autoZoom is enabled)
                    if (this.autoZoom && this.routeLayer) {
                        const bounds = getBoundsFromLayer(this.routeLayer, 'routeLayer');
                        if (bounds) {
                            fitMapToBounds(this.map, bounds);
                        }
                    }
                }
            }

            // Display property information
            if (data.matrikkelenhet_vector && data.matrikkelenhet_vector.length > 0) {
                this.displayMatrikkelenhetLayer(data);
            }

            // Load and display segments (only if showSegments is enabled)
            if (this.showSegments) {
                try {
                    await this.loadRouteSegments(rutenummer);
                } catch (error) {
                    console.warn('Failed to load segments:', error);
                    // Don't fail route loading if segments fail
                }
            }

            // Final check before returning - ensure this load wasn't cancelled
            if (this._currentLoadId !== loadId) {
                console.log('RouteViewer.loadRoute: Load cancelled before completion');
                // Clean up any layers that were added
                this.clear();
                this._loadingSpecificRoute = false; // Re-enable bbox loading
                return null;
            }

            this._isLoading = false;

            // Re-enable bbox loading immediately after route is loaded
            // The _isLoading check will prevent reloading during actual loading
            this._loadingSpecificRoute = false;

            // Reload bbox routes after a short delay to allow zoom to complete
            // This ensures bbox routes are visible in the new view
            setTimeout(() => {
                // Only reload if map hasn't been moved by user (check if still in similar view)
                // For now, just reload to ensure routes are visible
                if (this.map && !this._isLoading) {
                    // Get current filters from the map if available, or use defaults
                    const currentFilters = this._lastBboxFilters || {};
                    this.loadRoutesInBboxDebounced(currentFilters);
                }
            }, 500); // Short delay to allow zoom animation to start

            return data;
        } catch (error) {
            // Only throw error if this is still the current load
            if (this._currentLoadId === loadId) {
                this._isLoading = false;
                this._loadingSpecificRoute = false; // Re-enable bbox loading on error
                console.error('Error loading route:', error);
                throw error;
            } else {
                console.log('RouteViewer.loadRoute: Error in cancelled load, ignoring');
                this._loadingSpecificRoute = false; // Re-enable bbox loading
                return null;
            }
        } finally {
            this._isLoading = false;
        }
    }

    /**
     * Load and display route segments individually
     * @param {string} rutenummer - Route identifier
     */
    async loadRouteSegments(rutenummer) {
        // Store current load ID to check if cancelled
        const loadId = this._currentLoadId;

        try {
            const segmentsData = await loadRouteSegmentsData(rutenummer);

            // Check if load was cancelled
            if (this._currentLoadId !== loadId) {
                console.log('RouteViewer.loadRouteSegments: Load cancelled');
                return;
            }

            this.displaySegments(segmentsData);
        } catch (error) {
            // Only log error if this is still the current load
            if (this._currentLoadId === loadId) {
                console.error('Error loading segments:', error);
                throw error;
            } else {
                console.log('RouteViewer.loadRouteSegments: Error in cancelled load, ignoring');
            }
        }
    }

    /**
     * Display segments individually with different colors
     * @param {Object} segmentsData - Segments data from API
     */
    displaySegments(segmentsData) {
        // Only display segments if showSegments is enabled
        if (!this.showSegments) {
            return;
        }

        const segments = segmentsData.segments;

        if (!segments || segments.length === 0) {
            return;
        }

        // Create a new layer group for segments
        this.segmentLayerGroup = L.layerGroup();

        // Generate colors for segments (from constants)
        const segmentColors = SEGMENT_COLORS;

        segments.forEach((segment, index) => {
            const color = segmentColors[index % segmentColors.length];
            const geometry = segment.geometry;

            if (geometry && geometry.coordinates) {
                const popupContent = `
                    <strong>Segment ${segment.objid}</strong><br>
                    Lengde: ${segment.length_km.toFixed(2)} km (${segment.length_meters.toFixed(0)} m)
                `;
                const geoJsonLayer = createGeoJSONLayer(geometry, {
                    style: {
                        color: color,
                        weight: 5,
                        opacity: 0.9
                    },
                    popupContent: popupContent,
                    layerGroup: this.segmentLayerGroup,
                    layerName: `segment-${segment.objid}`
                });
                if (!geoJsonLayer) {
                    console.error(`Error displaying segment ${segment.objid}`);
                }
            }
        });

        // Add the layer group to the map
        this.segmentLayerGroup.addTo(this.map);

        // Add to layers control
        this.layerControl.addOverlay(this.segmentLayerGroup, `Segmenter (${segments.length})`);

        // Fit map to both route and segments if route layer exists (only if autoZoom is enabled)
        if (this.autoZoom && this.segmentLayerGroup.getLayers().length > 0) {
            const routeBounds = getBoundsFromLayer(this.routeLayer, 'routeLayer');
            const segmentBounds = getBoundsFromLayer(this.segmentLayerGroup, 'segmentLayerGroup');

            if (routeBounds && segmentBounds) {
                // Combine both bounds
                const allBounds = combineBounds([routeBounds, segmentBounds]);
                if (allBounds) {
                    fitMapToBounds(this.map, allBounds);
                }
            } else if (segmentBounds) {
                // Only segments available
                fitMapToBounds(this.map, segmentBounds);
            }
        }
    }

    /**
     * Display matrikkelenhet as separate layer group
     * @param {Object} data - Route data with matrikkelenhet_vector
     */
    displayMatrikkelenhetLayer(data) {
        const properties = data.matrikkelenhet_vector;

        if (!properties || properties.length === 0) {
            console.log('displayMatrikkelenhetLayer: No properties to display');
            return;
        }

        console.log(`displayMatrikkelenhetLayer: Displaying ${properties.length} properties`);

        // Create layer group for matrikkelenhet
        this.propertyLayerGroup = L.layerGroup();

        // Group consecutive properties with same matrikkelenhet
        const propertyGroups = [];
        const firstProp = properties[0];

        // Defensive checks for first property (even though we checked array length above)
        if (!firstProp || firstProp.matrikkelenhet === undefined || firstProp.offset_meters === undefined) {
            console.warn('displayMatrikkelenhetLayer: First property is missing required fields');
            return;
        }

        let currentGroup = {
            matrikkelenhet: firstProp.matrikkelenhet,
            bruksnavn: firstProp.bruksnavn || null,
            geometries: firstProp.geometry ? [firstProp.geometry] : [],
            startOffset: firstProp.offset_meters,
            endOffset: firstProp.offset_meters + (firstProp.length_meters || 0),
            color: getColorForProperty(firstProp.matrikkelenhet, this.colors)
        };

        for (let i = 1; i < properties.length; i++) {
            const prop = properties[i];

            // Skip invalid properties
            if (!prop || prop.offset_meters === undefined || prop.matrikkelenhet === undefined) {
                console.warn(`displayMatrikkelenhetLayer: Skipping invalid property at index ${i}`);
                continue;
            }

            const gap = prop.offset_meters - currentGroup.endOffset;

            if (gap < 10 && prop.matrikkelenhet === currentGroup.matrikkelenhet) {
                // Merge with current group
                if (prop.geometry) {
                    currentGroup.geometries.push(prop.geometry);
                }
                currentGroup.endOffset = prop.offset_meters + (prop.length_meters || 0);
            } else {
                // Start new group
                propertyGroups.push(currentGroup);
                currentGroup = {
                    matrikkelenhet: prop.matrikkelenhet,
                    bruksnavn: prop.bruksnavn || null,
                    geometries: prop.geometry ? [prop.geometry] : [],
                    startOffset: prop.offset_meters,
                    endOffset: prop.offset_meters + (prop.length_meters || 0),
                    color: getColorForProperty(prop.matrikkelenhet, this.colors)
                };
            }
        }
        propertyGroups.push(currentGroup);

        // Draw property segments using geometry directly from backend
        propertyGroups.forEach((group) => {
            if (group.geometries.length === 0) {
                return;
            }

            // Create GeoJSON layer for each geometry (or combine if multiple)
            group.geometries.forEach((geom) => {
                if (geom && geom.coordinates) {
                    const popupContent = `
                        <strong>${group.matrikkelenhet}</strong><br>
                        ${group.bruksnavn || ''}<br>
                        ${(group.endOffset - group.startOffset).toFixed(0)} m
                    `;
                    const geoJsonLayer = createGeoJSONLayer(geom, {
                        style: {
                            color: group.color,
                            weight: 4,
                            opacity: 0.6
                        },
                        popupContent: popupContent,
                        layerGroup: this.propertyLayerGroup,
                        layerName: `property-${group.matrikkelenhet}`
                    });
                    if (!geoJsonLayer) {
                        console.warn(`Failed to create layer for property ${group.matrikkelenhet}`);
                    }
                }
            });
        });

        // Add layer group to map and layers control
        const layerCount = this.propertyLayerGroup.getLayers().length;
        console.log(`displayMatrikkelenhetLayer: Created ${layerCount} property segments`);
        if (layerCount > 0) {
            this.propertyLayerGroup.addTo(this.map);
            this.layerControl.addOverlay(this.propertyLayerGroup, 'Grunneiere');

            // Ensure property layers appear on top of bbox routes
            this.propertyLayerGroup.eachLayer(layer => {
                if (layer.bringToFront) {
                    layer.bringToFront();
                }
                if (layer.setZIndex) {
                    layer.setZIndex(1000); // Higher than bbox routes (100)
                }
            });

            console.log('displayMatrikkelenhetLayer: Property layer group added to map and layer control');
        } else {
            console.warn('displayMatrikkelenhetLayer: No property segments created');
        }
    }

    /**
     * Get current route data
     * @returns {Object|null} Current route data
     */
    getCurrentRouteData() {
        return this.currentRouteData;
    }

    /**
     * Handle route click - check for overlapping routes and show selector if needed
     * @param {Event} e - Click event
     * @param {string} clickedRutenummer - Route number that was clicked
     */
    handleRouteClick(e, clickedRutenummer) {
        const clickPoint = e.latlng;
        const clickedRoute = this.routeDataMap.get(clickedRutenummer);

        if (!clickedRoute || !clickedRoute.geometry) {
            // Fallback to direct load
            this.loadRouteDirectly(clickedRutenummer);
            return;
        }

        // Find all routes that might overlap at this point
        const overlappingRoutes = [];

        // Check all routes to see if they contain this point
        this.routeDataMap.forEach((route, rutenummer) => {
            if (this.isPointOnRoute(clickPoint, route.geometry)) {
                overlappingRoutes.push({
                    rutenummer: rutenummer,
                    rutenavn: route.rutenavn || 'Ingen navn',
                    distance: route.total_length_km || 0,
                    vedlikeholdsansvarlig: route.vedlikeholdsansvarlig || 'Ukjent'
                });
            }
        });

        // If only one route, load it directly
        if (overlappingRoutes.length === 1) {
            this.loadRouteDirectly(clickedRutenummer);
        } else if (overlappingRoutes.length > 1) {
            // Show route selector
            this.showRouteSelector(e, overlappingRoutes);
        } else {
            // Fallback
            this.loadRouteDirectly(clickedRutenummer);
        }
    }

    /**
     * Check if a point is on a route geometry (simplified check)
     * @param {L.LatLng} point - Point to check
     * @param {Object} geometry - GeoJSON geometry
     * @returns {boolean} True if point is likely on the route
     */
    isPointOnRoute(point, geometry) {
        if (!geometry || !geometry.coordinates) return false;

        const tolerance = 0.001; // ~100 meters
        const processCoordinates = (coords) => {
            if (Array.isArray(coords[0]) && Array.isArray(coords[0][0])) {
                // MultiLineString
                return coords.some(coordArray => processCoordinates(coordArray));
            } else if (Array.isArray(coords[0]) && typeof coords[0][0] === 'number') {
                // LineString - check if point is near any segment
                for (let i = 0; i < coords.length - 1; i++) {
                    const [lng1, lat1] = coords[i];
                    const [lng2, lat2] = coords[i + 1];

                    // Simple distance check - if point is close to line segment
                    const dist1 = Math.sqrt(Math.pow(point.lat - lat1, 2) + Math.pow(point.lng - lng1, 2));
                    const dist2 = Math.sqrt(Math.pow(point.lat - lat2, 2) + Math.pow(point.lng - lng2, 2));

                    if (dist1 < tolerance || dist2 < tolerance) {
                        return true;
                    }
                }
            }
            return false;
        };

        return processCoordinates(geometry.coordinates);
    }

    /**
     * Show route selector popup for overlapping routes
     * @param {Event} e - Click event
     * @param {Array} routes - Array of overlapping routes
     */
    showRouteSelector(e, routes) {
        // Remove existing selector if any
        if (this.routeSelectorPopup) {
            this.map.removeLayer(this.routeSelectorPopup);
        }

        // Sort routes by name for better UX
        routes.sort((a, b) => a.rutenummer.localeCompare(b.rutenummer));

        // Create selector HTML
        let selectorHTML = `
            <div style="min-width: 250px; max-height: 400px; overflow-y: auto;">
                <h4 style="margin: 0 0 10px 0; font-size: 1rem;">Flere ruter på dette punktet:</h4>
                <div style="display: flex; flex-direction: column; gap: 5px;">
        `;

        routes.forEach((route, index) => {
            selectorHTML += `
                <button
                    class="route-selector-btn"
                    data-rutenummer="${route.rutenummer}"
                    style="
                        text-align: left;
                        padding: 8px 12px;
                        border: 1px solid #ddd;
                        border-radius: 4px;
                        background: white;
                        cursor: pointer;
                        transition: background 0.2s;
                    "
                    onmouseover="this.style.background='#f0f0f0'"
                    onmouseout="this.style.background='white'"
                >
                    <strong>${route.rutenummer}</strong><br>
                    <small style="color: #666;">${route.rutenavn}</small><br>
                    <small style="color: #999;">${route.distance.toFixed(2)} km • ${route.vedlikeholdsansvarlig}</small>
                </button>
            `;
        });

        selectorHTML += `
                </div>
                <div style="margin-top: 10px; font-size: 0.85em; color: #666;">
                    Bruk piltaster for å navigere, Enter for å velge
                </div>
            </div>
        `;

        // Create popup
        const popup = L.popup({
            maxWidth: 300,
            className: 'route-selector-popup'
        })
        .setLatLng(e.latlng)
        .setContent(selectorHTML)
        .openOn(this.map);

        this.routeSelectorPopup = popup;

        // Add click handlers to buttons
        setTimeout(() => {
            const buttons = document.querySelectorAll('.route-selector-btn');
            let selectedIndex = 0;

            buttons.forEach((btn, index) => {
                btn.addEventListener('click', () => {
                    const rutenummer = btn.dataset.rutenummer;
                    this.loadRouteDirectly(rutenummer);
                    this.map.closePopup();
                });

                // Keyboard navigation
                btn.addEventListener('keydown', (keyEvent) => {
                    if (keyEvent.key === 'ArrowDown') {
                        keyEvent.preventDefault();
                        selectedIndex = Math.min(selectedIndex + 1, buttons.length - 1);
                        buttons[selectedIndex].focus();
                    } else if (keyEvent.key === 'ArrowUp') {
                        keyEvent.preventDefault();
                        selectedIndex = Math.max(selectedIndex - 1, 0);
                        buttons[selectedIndex].focus();
                    } else if (keyEvent.key === 'Enter') {
                        keyEvent.preventDefault();
                        btn.click();
                    }
                });
            });

            // Focus first button
            if (buttons.length > 0) {
                buttons[0].focus();
            }
        }, 100);
    }

    /**
     * Load route directly (used by selector and single-route clicks)
     * @param {string} rutenummer - Route number to load
     */
    loadRouteDirectly(rutenummer) {
        console.log(`Loading full route details for: ${rutenummer}`);
        if (typeof window !== 'undefined' && window.loadRoute) {
            window.loadRoute(rutenummer);
        } else {
            this.loadRoute(rutenummer);
        }
    }
}

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = RouteViewer;
}

