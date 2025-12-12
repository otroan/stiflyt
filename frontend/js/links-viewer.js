/**
 * Links viewer functionality - displays network links on the map
 */

class LinksViewer {
    constructor(map, layerControl, options = {}) {
        this.map = map;
        this.layerControl = layerControl;
        this.linksLayerGroup = null;
        this.enabled = options.enabled !== false; // Default to enabled
        this.links = new Map(); // Map of link_id -> layer for quick lookup

        // Debounce timer for bounding box queries
        this._bboxQueryTimer = null;
        this._bboxQueryDelay = 300; // 300ms delay for links (can be heavier than routes)

        // Track loading state
        this._isLoading = false;
    }

    /**
     * Clear all links layers from the map
     */
    clear() {
        if (this.linksLayerGroup) {
            this.linksLayerGroup.clearLayers();
            this.links.clear();
        }
    }

    /**
     * Remove links layer group from map and layer control
     */
    remove() {
        if (this.linksLayerGroup) {
            this.linksLayerGroup.clearLayers();
            this.map.removeLayer(this.linksLayerGroup);
            this.layerControl.removeLayer(this.linksLayerGroup);
            this.linksLayerGroup = null;
            this.links.clear();
        }
    }

    /**
     * Enable links display
     */
    enable() {
        this.enabled = true;
        // Reload links if map is already initialized
        if (this.map) {
            this.loadLinksInBboxDebounced();
        }
    }

    /**
     * Disable links display
     */
    disable() {
        this.enabled = false;
        this.remove();
    }

    /**
     * Debounced version of loadLinksInBbox to avoid too many API calls
     */
    loadLinksInBboxDebounced() {
        if (!this.enabled) {
            return;
        }

        // Clear any pending queries
        if (this._bboxQueryTimer) {
            clearTimeout(this._bboxQueryTimer);
            this._bboxQueryTimer = null;
        }

        // Schedule new query
        this._bboxQueryTimer = setTimeout(() => {
            this.loadLinksInBbox();
        }, this._bboxQueryDelay);
    }

    /**
     * Load links within the current map bounding box
     */
    async loadLinksInBbox() {
        if (!this.enabled) {
            return;
        }

        if (this._isLoading) {
            return;
        }

        this._isLoading = true;

        try {
            // Get current map bounds
            const bounds = this.map.getBounds();
            const bbox = {
                min_lat: bounds.getSouth(),
                min_lng: bounds.getWest(),
                max_lat: bounds.getNorth(),
                max_lng: bounds.getEast()
            };

            // Load links in bounding box
            // Note: Backend expects bbox in same SRID as links.geom (25833)
            // We pass WGS84 coordinates - backend should handle conversion
            const data = await loadLinksInBbox(bbox, { limit: 1000 });

            // Clear previous links
            this.clear();

            // Create layer group if it doesn't exist
            if (!this.linksLayerGroup) {
                this.linksLayerGroup = L.layerGroup().addTo(this.map);
                this.layerControl.addOverlay(this.linksLayerGroup, 'Nettverkslenker');
            }

            // Process features in batches to avoid blocking UI
            const features = data.features || [];
            const batchSize = 50;
            let batchIndex = 0;

            const processBatch = () => {
                const endIndex = Math.min(batchIndex + batchSize, features.length);

                for (let i = batchIndex; i < endIndex; i++) {
                    const feature = features[i];
                    if (!feature.geometry) {
                        continue; // Skip features without geometry
                    }

                    const linkId = feature.id;
                    const props = feature.properties || {};
                    const lengthM = props.length_m || 0;
                    const lengthKm = lengthM / 1000.0;
                    const aNode = props.a_node || 'N/A';
                    const bNode = props.b_node || 'N/A';

                    // Create popup content
                    const popupContent = `
                        <div style="min-width: 200px;">
                            <strong>Link ${linkId}</strong><br>
                            <small>
                                Node A: ${aNode}<br>
                                Node B: ${bNode}<br>
                                Lengde: ${lengthKm.toFixed(2)} km (${lengthM.toFixed(0)} m)
                            </small>
                        </div>
                    `;

                    // Create GeoJSON layer for this link
                    const linkLayer = createGeoJSONLayer(feature.geometry, {
                        style: {
                            color: '#e74c3c', // Red color for links
                            weight: 1.5,
                            opacity: 0.7,
                            fillOpacity: 0
                        },
                        popupContent: popupContent,
                        layerGroup: this.linksLayerGroup,
                        layerName: `link-${linkId}`
                    });

                    if (linkLayer) {
                        this.links.set(linkId, linkLayer);
                    }
                }

                batchIndex = endIndex;

                // Process next batch if there are more features
                if (batchIndex < features.length) {
                    requestAnimationFrame(processBatch);
                } else {
                    this._isLoading = false;
                    console.log(`Loaded ${features.length} links`);
                }
            };

            // Start processing batches
            if (features.length > 0) {
                processBatch();
            } else {
                this._isLoading = false;
            }
        } catch (error) {
            console.error('Error loading links:', error);
            this._isLoading = false;
        }
    }
}

