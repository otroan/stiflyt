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

        // Color palette for properties
        this.colors = [
            '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
            '#1abc9c', '#e67e22', '#34495e', '#16a085', '#27ae60',
            '#2980b9', '#8e44ad', '#c0392b', '#d35400', '#7f8c8d'
        ];
    }

    /**
     * Clear all route-related layers from the map
     */
    clear() {
        // Remove route layer
        if (this.routeLayer) {
            this.map.removeLayer(this.routeLayer);
            this.routeLayer = null;
        }

        // Remove route layer group (for disconnected components)
        if (this.routeLayerGroup) {
            this.layerControl.removeLayer(this.routeLayerGroup);
            this.map.removeLayer(this.routeLayerGroup);
            this.routeLayerGroup = null;
        }

        // Remove property layers
        this.propertyLayers.forEach(layer => {
            this.map.removeLayer(layer);
        });
        this.propertyLayers = [];

        if (this.propertyLayerGroup) {
            this.layerControl.removeLayer(this.propertyLayerGroup);
            this.map.removeLayer(this.propertyLayerGroup);
            this.propertyLayerGroup = null;
        }

        // Remove segment layer
        if (this.segmentLayerGroup) {
            this.layerControl.removeLayer(this.segmentLayerGroup);
            this.map.removeLayer(this.segmentLayerGroup);
            this.segmentLayerGroup = null;
        }

        // Remove markers
        this.markers.forEach(marker => {
            this.map.removeLayer(marker);
        });
        this.markers = [];

        this.currentRouteData = null;
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

        try {
            // Clear previous route
            this.clear();

            // Load route data
            const data = await loadRouteData(rutenummer);
            this.currentRouteData = data;

            // Display route geometry
            // If route has multiple components, display each as a separate layer (only if showComponents is enabled)
            if (data.geometry) {
                if (this.showComponents && data.components && data.components.length > 1) {
                    // Multiple disconnected components - display each separately
                    this.routeLayerGroup = L.layerGroup();

                    // Use different colors for each component
                    const colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#34495e'];

                    data.components.forEach((component, index) => {
                        // Build geometry for this component
                        const componentSegments = data.matrikkelenhet_vector
                            ? data.matrikkelenhet_vector.filter(item =>
                                component.includes(item.segment_objid || -1)
                            )
                            : [];

                        // For now, display the full geometry and let Leaflet handle MultiLineString
                        // Each component will be a separate part of the MultiLineString
                        const componentColor = colors[index % colors.length];

                        // Create a layer for this component
                        const componentLayer = L.geoJSON(data.geometry, {
                            style: {
                                color: componentColor,
                                weight: 4,
                                opacity: 0.8
                            }
                        });

                        // Add popup showing component info
                        componentLayer.bindPopup(`
                            <strong>Komponent ${index + 1}</strong><br>
                            Segmenter: ${component.length}<br>
                            ${data.metadata?.component_count ? `Totalt ${data.metadata.component_count} komponenter` : ''}
                        `);

                        componentLayer.addTo(this.routeLayerGroup);
                    });

                    this.routeLayerGroup.addTo(this.map);
                    this.layerControl.addOverlay(this.routeLayerGroup, `Rute (${data.components.length} komponenter)`);

                    // Fit map to all components (only if autoZoom is enabled)
                    if (this.autoZoom && this.routeLayerGroup.getLayers().length > 0 &&
                        typeof this.routeLayerGroup.getBounds === 'function') {
                        try {
                            const bounds = this.routeLayerGroup.getBounds();
                            if (bounds && bounds.isValid && bounds.isValid()) {
                                this.map.fitBounds(bounds, { padding: [50, 50] });
                            }
                        } catch (error) {
                            console.warn('Could not fit bounds to routeLayerGroup:', error);
                        }
                    }
                } else {
                    // Single connected route
                    this.routeLayer = displayRouteGeometry(this.map, data.geometry);

                    // Fit map to route bounds (only if autoZoom is enabled)
                    if (this.autoZoom && this.routeLayer && typeof this.routeLayer.getBounds === 'function') {
                        try {
                            const bounds = this.routeLayer.getBounds();
                            if (bounds && bounds.isValid && bounds.isValid()) {
                                this.map.fitBounds(bounds, { padding: [50, 50] });
                            }
                        } catch (error) {
                            console.warn('Could not fit bounds to routeLayer:', error);
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

            return data;
        } catch (error) {
            console.error('Error loading route:', error);
            throw error;
        }
    }

    /**
     * Load and display route segments individually
     * @param {string} rutenummer - Route identifier
     */
    async loadRouteSegments(rutenummer) {
        try {
            const segmentsData = await loadRouteSegmentsData(rutenummer);
            this.displaySegments(segmentsData);
        } catch (error) {
            console.error('Error loading segments:', error);
            throw error;
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

        // Generate colors for segments
        const segmentColors = [
            '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
            '#1abc9c', '#e67e22', '#34495e', '#16a085', '#27ae60',
            '#2980b9', '#8e44ad', '#c0392b', '#d35400', '#7f8c8d',
            '#e91e63', '#00bcd4', '#4caf50', '#ff9800', '#673ab7'
        ];

        segments.forEach((segment, index) => {
            const color = segmentColors[index % segmentColors.length];
            const geometry = segment.geometry;

            if (geometry && geometry.coordinates) {
                try {
                    const geoJsonLayer = L.geoJSON(geometry, {
                        style: {
                            color: color,
                            weight: 5,
                            opacity: 0.9
                        }
                    });

                    // Add popup with segment info
                    geoJsonLayer.bindPopup(`
                        <strong>Segment ${segment.objid}</strong><br>
                        Lengde: ${segment.length_km.toFixed(2)} km (${segment.length_meters.toFixed(0)} m)
                    `);

                    geoJsonLayer.addTo(this.segmentLayerGroup);
                } catch (error) {
                    console.error(`Error displaying segment ${segment.objid}:`, error);
                }
            }
        });

        // Add the layer group to the map
        this.segmentLayerGroup.addTo(this.map);

        // Add to layers control
        this.layerControl.addOverlay(this.segmentLayerGroup, `Segmenter (${segments.length})`);

        // Fit map to both route and segments if route layer exists (only if autoZoom is enabled)
        if (this.autoZoom && this.segmentLayerGroup.getLayers().length > 0) {
            try {
                if (this.routeLayer && typeof this.routeLayer.getBounds === 'function') {
                    const routeBounds = this.routeLayer.getBounds();
                    const segmentBounds = this.segmentLayerGroup.getBounds();
                    if (routeBounds && routeBounds.isValid && routeBounds.isValid() &&
                        segmentBounds && segmentBounds.isValid && segmentBounds.isValid()) {
                        const allBounds = L.latLngBounds([
                            routeBounds.getSouthWest(),
                            routeBounds.getNorthEast(),
                            segmentBounds.getSouthWest(),
                            segmentBounds.getNorthEast()
                        ]);
                        this.map.fitBounds(allBounds, { padding: [50, 50] });
                    }
                } else if (typeof this.segmentLayerGroup.getBounds === 'function') {
                    const segmentBounds = this.segmentLayerGroup.getBounds();
                    if (segmentBounds && segmentBounds.isValid && segmentBounds.isValid()) {
                        this.map.fitBounds(segmentBounds, { padding: [50, 50] });
                    }
                }
            } catch (error) {
                console.warn('Could not fit bounds to segments:', error);
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
        let currentGroup = {
            matrikkelenhet: properties[0].matrikkelenhet,
            bruksnavn: properties[0].bruksnavn,
            geometries: properties[0].geometry ? [properties[0].geometry] : [],
            startOffset: properties[0].offset_meters,
            endOffset: properties[0].offset_meters + properties[0].length_meters,
            color: getColorForProperty(properties[0].matrikkelenhet, this.colors)
        };

        for (let i = 1; i < properties.length; i++) {
            const prop = properties[i];
            const gap = prop.offset_meters - currentGroup.endOffset;

            if (gap < 10 && prop.matrikkelenhet === currentGroup.matrikkelenhet) {
                // Merge with current group
                if (prop.geometry) {
                    currentGroup.geometries.push(prop.geometry);
                }
                currentGroup.endOffset = prop.offset_meters + prop.length_meters;
            } else {
                // Start new group
                propertyGroups.push(currentGroup);
                currentGroup = {
                    matrikkelenhet: prop.matrikkelenhet,
                    bruksnavn: prop.bruksnavn,
                    geometries: prop.geometry ? [prop.geometry] : [],
                    startOffset: prop.offset_meters,
                    endOffset: prop.offset_meters + prop.length_meters,
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
                    const geoJsonLayer = L.geoJSON(geom, {
                        style: {
                            color: group.color,
                            weight: 4,
                            opacity: 0.6
                        }
                    });

                    geoJsonLayer.bindPopup(`
                        <strong>${group.matrikkelenhet}</strong><br>
                        ${group.bruksnavn || ''}<br>
                        ${(group.endOffset - group.startOffset).toFixed(0)} m
                    `);

                    geoJsonLayer.addTo(this.propertyLayerGroup);
                }
            });
        });

        // Add layer group to map and layers control
        const layerCount = this.propertyLayerGroup.getLayers().length;
        console.log(`displayMatrikkelenhetLayer: Created ${layerCount} property segments`);
        if (layerCount > 0) {
            this.propertyLayerGroup.addTo(this.map);
            this.layerControl.addOverlay(this.propertyLayerGroup, 'Grunneiere');
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

