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
        this.linkData = new Map(); // Map of link_id -> feature data

        // Selected links management
        this.selectedLinks = new Set(); // Set of selected link_ids
        this.selectionMode = true; // Selection mode is always active by default
        this.onSelectionChange = null; // Callback when selection changes

        // Debounce timer for bounding box queries
        this._bboxQueryTimer = null;
        this._bboxQueryDelay = 300; // 300ms delay for links (can be heavier than routes)

        // Track loading state
        this._isLoading = false;
    }

    /**
     * Clear all links layers from the map
     * @param {boolean} preserveSelection - If true, preserve selectedLinks when clearing
     */
    clear(preserveSelection = false) {
        if (this.linksLayerGroup) {
            this.linksLayerGroup.clearLayers();
            this.links.clear();
            this.linkData.clear();
        }
        if (!preserveSelection) {
            this.selectedLinks.clear();
        }
    }

    /**
     * Enable/disable selection mode
     */
    setSelectionMode(enabled) {
        this.selectionMode = enabled;
        this.updateLinkStyles();
    }

    /**
     * Clear all selected links
     */
    clearSelection() {
        this.selectedLinks.clear();
        this.updateLinkStyles();
        if (this.onSelectionChange) {
            this.onSelectionChange(Array.from(this.selectedLinks));
        }
    }

    /**
     * Toggle selection of a link
     * Selection is always enabled, but we check selectionMode for compatibility
     */
    toggleLinkSelection(linkId) {
        // Selection is always enabled, but keep check for compatibility
        if (!this.selectionMode) {
            return;
        }

        if (this.selectedLinks.has(linkId)) {
            this.selectedLinks.delete(linkId);
        } else {
            this.selectedLinks.add(linkId);
        }

        this.updateLinkStyle(linkId);

        if (this.onSelectionChange) {
            this.onSelectionChange(Array.from(this.selectedLinks));
        }
    }

    /**
     * Get selected links data
     */
    getSelectedLinksData() {
        return Array.from(this.selectedLinks).map(linkId => {
            const linkData = this.linkData.get(linkId);
            if (!linkData) {
                console.warn(`Link data not found for linkId: ${linkId}`);
                return null;
            }
            if (!linkData.geometry) {
                console.warn(`Link ${linkId} has no geometry:`, linkData);
                return null;
            }
            return linkData;
        }).filter(Boolean);
    }

    /**
     * Update style for a specific link based on selection state
     */
    updateLinkStyle(linkId) {
        const layer = this.links.get(linkId);
        if (!layer) return;

        const isSelected = this.selectedLinks.has(linkId);

            if (layer.eachLayer) {
                // MultiLineString - update each layer
                layer.eachLayer((subLayer) => {
                    if (isSelected) {
                        subLayer.setStyle({
                            color: '#27ae60', // Green for selected
                            weight: 5,  // Increased from 3
                            opacity: 1.0
                        });
                    } else {
                        subLayer.setStyle({
                            color: '#e74c3c', // Red for unselected
                            weight: 3,  // Increased from 1.5
                            opacity: 0.7
                        });
                    }
                });
            } else {
                // Single layer
                if (isSelected) {
                    layer.setStyle({
                        color: '#27ae60', // Green for selected
                        weight: 5,  // Increased from 3
                        opacity: 1.0
                    });
                } else {
                    layer.setStyle({
                        color: '#e74c3c', // Red for unselected
                        weight: 3,  // Increased from 1.5
                        opacity: 0.7
                    });
                }
            }
    }

    /**
     * Update styles for all links based on selection state
     */
    updateLinkStyles() {
        for (const linkId of this.links.keys()) {
            this.updateLinkStyle(linkId);
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

            // Preserve selection when reloading (user might have selected links)
            const preservedSelection = new Set(this.selectedLinks);

            // Clear previous links but preserve selection
            this.clear(true);

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
                    const routes = props.routes || []; // Array of route info objects

                    // Store feature data
                    this.linkData.set(linkId, feature);

                    // Create tooltip content with route information
                    let tooltipContent = null;
                    if (routes && routes.length > 0) {
                        // Build tooltip with route information
                        const routeList = routes.map(route => {
                            const rutenummer = route.rutenummer || 'Ukjent';
                            const rutenavn = route.rutenavn || 'Ingen navn';
                            const rutetype = route.rutetype || '';
                            const vedlikeholdsansvarlig = route.vedlikeholdsansvarlig || '';
                            const typeLabel = rutetype ? ` (${rutetype})` : '';
                            const ansvarligLabel = vedlikeholdsansvarlig ? `<br><small style="color: #666;">${vedlikeholdsansvarlig}</small>` : '';
                            return `<div style="margin: 3px 0; padding-bottom: 3px; border-bottom: 1px solid #eee;">
                                <strong>${rutenummer}</strong>${typeLabel}<br>
                                <small>${rutenavn}</small>${ansvarligLabel}
                            </div>`;
                        }).join('');

                        tooltipContent = `
                            <div style="max-width: 400px;">
                                <strong>Link ${linkId}</strong><br>
                                <small>Lengde: ${lengthKm.toFixed(2)} km</small>
                                ${routes.length > 1 ? `<br><strong>Ruter (${routes.length}):</strong>` : '<br><strong>Rute:</strong>'}
                                ${routeList}
                            </div>
                        `;
                    } else {
                        // No routes, show basic info
                        tooltipContent = `
                            <div style="max-width: 200px;">
                                <strong>Link ${linkId}</strong><br>
                                <small>Lengde: ${lengthKm.toFixed(2)} km</small><br>
                                <small style="color: #999;">Ingen ruter</small>
                            </div>
                        `;
                    }

                    // No popup needed - only tooltip on hover and click for selection
                    const isSelected = this.selectedLinks.has(linkId);

                    // Determine initial style based on selection state
                    // Make links wider for easier clicking
                    const initialStyle = {
                        color: isSelected ? '#27ae60' : '#e74c3c',
                        weight: isSelected ? 5 : 3,  // Increased from 3/1.5 to 5/3
                        opacity: isSelected ? 1.0 : 0.7,
                        fillOpacity: 0
                    };

                    // Create GeoJSON layer for this link
                    const linkLayer = createGeoJSONLayer(feature.geometry, {
                        style: initialStyle,
                        tooltipContent: tooltipContent, // Only tooltip for mouseover
                        layerGroup: this.linksLayerGroup,
                        layerName: `link-${linkId}`
                    });

                    if (linkLayer) {
                        this.links.set(linkId, linkLayer);

                        // Add click handler for selection and bind tooltips
                        // Tooltips must be bound AFTER layer is on map to work properly
                        setTimeout(() => {
                            if (linkLayer.eachLayer) {
                                linkLayer.eachLayer((layer) => {
                                    // Bind tooltip if pending
                                    if (layer._pendingTooltipContent && layer.bindTooltip) {
                                        try {
                                            layer.bindTooltip(layer._pendingTooltipContent, {
                                                permanent: false,
                                                direction: 'auto',
                                                className: 'link-tooltip',
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
                                            console.error('Error binding tooltip to link layer:', error);
                                        }
                                    }

                                    // Click handler for selection only (no popup)
                                    layer.on('click', (e) => {
                                        L.DomEvent.stopPropagation(e);
                                        this.toggleLinkSelection(linkId);
                                    });
                                });
                            } else {
                                // Single layer
                                if (linkLayer._pendingTooltipContent && linkLayer.bindTooltip) {
                                    try {
                                        linkLayer.bindTooltip(linkLayer._pendingTooltipContent, {
                                            permanent: false,
                                            direction: 'auto',
                                            className: 'link-tooltip',
                                            opacity: 0.95,
                                            offset: [0, -5]
                                        });

                                        linkLayer.on('mouseover', function(e) {
                                            if (this.openTooltip) {
                                                this.openTooltip(e.latlng);
                                            }
                                        });
                                        linkLayer.on('mouseout', function(e) {
                                            if (this.closeTooltip) {
                                                this.closeTooltip();
                                            }
                                        });

                                        delete linkLayer._pendingTooltipContent;
                                    } catch (error) {
                                        console.error('Error binding tooltip to single link layer:', error);
                                    }
                                }

                                linkLayer.on('click', (e) => {
                                    L.DomEvent.stopPropagation(e);
                                    this.toggleLinkSelection(linkId);
                                });
                            }
                        }, 50);
                    }
                }

                batchIndex = endIndex;

                // Process next batch if there are more features
                if (batchIndex < features.length) {
                    requestAnimationFrame(processBatch);
                } else {
                    this._isLoading = false;
                    console.log(`Loaded ${features.length} links`);

                    // Restore selection state for links that are still loaded
                    // Only restore if links are actually in the current view
                    const linksToRestore = [];
                    for (const linkId of preservedSelection) {
                        if (this.links.has(linkId) && this.linkData.has(linkId)) {
                            linksToRestore.push(linkId);
                        }
                    }

                    // Restore selection
                    this.selectedLinks.clear();
                    for (const linkId of linksToRestore) {
                        this.selectedLinks.add(linkId);
                        this.updateLinkStyle(linkId);
                    }

                    // Notify selection change if any links were restored
                    if (linksToRestore.length > 0 && this.onSelectionChange) {
                        this.onSelectionChange(Array.from(this.selectedLinks));
                    }
                }
            };

            // Start processing batches
            if (features.length > 0) {
                processBatch();
            } else {
                this._isLoading = false;

                // Restore selection even if no features (in case selection was cleared)
                const linksToRestore = [];
                for (const linkId of preservedSelection) {
                    if (this.links.has(linkId) && this.linkData.has(linkId)) {
                        linksToRestore.push(linkId);
                    }
                }

                if (linksToRestore.length > 0) {
                    this.selectedLinks.clear();
                    for (const linkId of linksToRestore) {
                        this.selectedLinks.add(linkId);
                        this.updateLinkStyle(linkId);
                    }
                    if (this.onSelectionChange) {
                        this.onSelectionChange(Array.from(this.selectedLinks));
                    }
                }
            }
        } catch (error) {
            console.error('Error loading links:', error);
            this._isLoading = false;
        }
    }
}

