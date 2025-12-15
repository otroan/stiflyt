/**
 * Anchor nodes viewer functionality - displays anchor nodes as circular markers on the map
 */

class AnchorNodesViewer {
    constructor(map, layerControl, linksViewer = null, options = {}) {
        this.map = map;
        this.layerControl = layerControl;
        this.linksViewer = linksViewer; // Reference to LinksViewer to show connections
        this.nodesLayerGroup = null;
        this.enabled = options.enabled !== false; // Default to enabled
        this.nodes = new Map(); // Map of node_id -> marker
        this.nodeData = new Map(); // Map of node_id -> feature data

        // Debounce timer for bounding box queries
        this._bboxQueryTimer = null;
        this._bboxQueryDelay = 300; // 300ms delay

        // Track loading state
        this._isLoading = false;
    }

    /**
     * Clear all anchor node markers from the map
     */
    clear() {
        if (this.nodesLayerGroup) {
            this.nodesLayerGroup.clearLayers();
            this.nodes.clear();
            this.nodeData.clear();
        }
    }

    /**
     * Remove anchor nodes layer group from map and layer control
     */
    remove() {
        if (this.nodesLayerGroup) {
            this.nodesLayerGroup.clearLayers();
            this.map.removeLayer(this.nodesLayerGroup);
            this.layerControl.removeLayer(this.nodesLayerGroup);
            this.nodesLayerGroup = null;
            this.nodes.clear();
        }
    }

    /**
     * Enable anchor nodes display
     */
    enable() {
        this.enabled = true;
        // Reload nodes if map is already initialized
        if (this.map) {
            this.loadAnchorNodesInBboxDebounced();
        }
    }

    /**
     * Disable anchor nodes display
     */
    disable() {
        this.enabled = false;
        this.remove();
    }

    /**
     * Debounced version of loadAnchorNodesInBbox to avoid too many API calls
     */
    loadAnchorNodesInBboxDebounced() {
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
            this.loadAnchorNodesInBbox();
        }, this._bboxQueryDelay);
    }

    /**
     * Find links connected to a node
     */
    getConnectedLinks(nodeId) {
        if (!this.linksViewer) {
            return [];
        }

        const connectedLinks = [];
        for (const [linkId, linkFeature] of this.linksViewer.linkData.entries()) {
            const props = linkFeature.properties || {};
            if (props.a_node === nodeId || props.b_node === nodeId) {
                connectedLinks.push({
                    linkId: linkId,
                    isA: props.a_node === nodeId,
                    isB: props.b_node === nodeId
                });
            }
        }
        return connectedLinks;
    }

    /**
     * Load anchor nodes within the current map bounding box
     */
    async loadAnchorNodesInBbox() {
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

            // Load anchor nodes in bounding box
            const data = await loadAnchorNodes({ bbox, limit: 1000 });

            // Clear previous nodes
            this.clear();

            // Create layer group if it doesn't exist
            if (!this.nodesLayerGroup) {
                this.nodesLayerGroup = L.layerGroup().addTo(this.map);
                this.layerControl.addOverlay(this.nodesLayerGroup, 'Ankerpunkter');
            }

            // Process features
            const features = data.features || [];
            for (const feature of features) {
                if (!feature.geometry || feature.geometry.type !== 'Point') {
                    continue; // Skip features without Point geometry
                }

                const nodeId = feature.id || feature.properties?.node_id;
                if (!nodeId) {
                    continue;
                }

                const props = feature.properties || {};
                const navn = props.navn || null;
                const navnKilde = props.navn_kilde || null;
                const navnDistanceM = props.navn_distance_m || null;

                // Store feature data
                this.nodeData.set(nodeId, feature);

                // Get coordinates (GeoJSON Point is [lng, lat])
                const coords = feature.geometry.coordinates;
                const lat = coords[1];
                const lng = coords[0];

                // Create circular marker
                const marker = L.circleMarker([lat, lng], {
                    radius: 6, // Small circular marker
                    fillColor: '#3498db', // Blue color
                    color: '#2980b9', // Darker blue border
                    weight: 2,
                    opacity: 0.8,
                    fillOpacity: 0.6
                });

                // Build tooltip content
                let tooltipContent = `<div style="max-width: 250px;">`;
                tooltipContent += `<strong>Ankerpunkt ${nodeId}</strong><br>`;

                if (navn) {
                    tooltipContent += `<strong>${navn}</strong><br>`;
                    if (navnKilde) {
                        tooltipContent += `<small style="color: #666;">Kilde: ${navnKilde}</small><br>`;
                    }
                    if (navnDistanceM !== null) {
                        tooltipContent += `<small style="color: #666;">Avstand: ${navnDistanceM.toFixed(0)} m</small><br>`;
                    }
                } else {
                    tooltipContent += `<small style="color: #999;">Ingen navn</small><br>`;
                }

                // Show connected links if available
                const connectedLinks = this.getConnectedLinks(nodeId);
                if (connectedLinks.length > 0) {
                    tooltipContent += `<br><small style="color: #666;"><strong>Koblet til ${connectedLinks.length} lenke(r):</strong></small><br>`;
                    connectedLinks.slice(0, 5).forEach(link => {
                        tooltipContent += `<small style="color: #666;">• Link ${link.linkId} (${link.isA ? 'A' : 'B'}-node)</small><br>`;
                    });
                    if (connectedLinks.length > 5) {
                        tooltipContent += `<small style="color: #666;">... og ${connectedLinks.length - 5} flere</small>`;
                    }
                }

                tooltipContent += `</div>`;

                // Bind tooltip
                marker.bindTooltip(tooltipContent, {
                    permanent: false,
                    direction: 'auto',
                    className: 'anchor-node-tooltip',
                    opacity: 0.95,
                    offset: [0, -5]
                });

                // No hover effects - tooltip only

                // Store connected links on marker for hover effects
                marker._connectedLinks = connectedLinks;

                // Add to layer group
                marker.addTo(this.nodesLayerGroup);
                this.nodes.set(nodeId, marker);
            }

            this._isLoading = false;
            console.log(`Loaded ${features.length} anchor nodes`);
        } catch (error) {
            console.error('Error loading anchor nodes:', error);
            this._isLoading = false;
        }
    }
}

