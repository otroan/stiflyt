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



}

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = RouteViewer;
}

