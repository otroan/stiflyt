/**
 * Debug viewer functionality - displays route debugging information
 */

class DebugViewer {
    constructor(map, layerControl) {
        this.map = map;
        this.layerControl = layerControl;
        this.debugLayerGroup = null;
        this.connectionLayerGroup = null;
    }

    /**
     * Clear all debug layers from the map
     */
    clear() {
        if (this.debugLayerGroup) {
            this.layerControl.removeLayer(this.debugLayerGroup);
            this.map.removeLayer(this.debugLayerGroup);
            this.debugLayerGroup = null;
        }

        if (this.connectionLayerGroup) {
            this.layerControl.removeLayer(this.connectionLayerGroup);
            this.map.removeLayer(this.connectionLayerGroup);
            this.connectionLayerGroup = null;
        }
    }

    /**
     * Load and display route debugging information
     * @param {string} rutenummer - Route identifier
     */
    async loadRouteDebug(rutenummer) {
        try {
            const debugData = await loadRouteDebugData(rutenummer);
            this.displayDebugSegments(debugData);
            return debugData;
        } catch (error) {
            console.error('Error loading debug info:', error);
            throw error;
        }
    }

    /**
     * Display debug segments with issues
     * @param {Object} debugData - Debug data from API
     */
    displayDebugSegments(debugData) {
        const segments = debugData.segments;
        const connections = debugData.connections || [];

        if (!segments || segments.length === 0) {
            return;
        }

        // Create layer groups
        this.debugLayerGroup = L.layerGroup();
        this.connectionLayerGroup = L.layerGroup();

        // Display segments with issues
        segments.forEach((segment) => {
            const geometry = segment.geometry;
            const issues = segment.issues || [];

            if (geometry && geometry.coordinates) {
                try {
                    // Determine color based on issues
                    let color = '#95a5a6'; // Default gray
                    let weight = 4;
                    let opacity = 0.7;

                    const hasError = issues.some(i => i.severity === 'ERROR');
                    const hasWarning = issues.some(i => i.severity === 'WARNING');

                    if (hasError) {
                        color = '#e74c3c'; // Red
                        weight = 6;
                        opacity = 0.9;
                    } else if (hasWarning) {
                        color = '#f39c12'; // Orange
                        weight = 5;
                        opacity = 0.8;
                    }

                    const geoJsonLayer = L.geoJSON(geometry, {
                        style: {
                            color: color,
                            weight: weight,
                            opacity: opacity
                        }
                    });

                    // Build popup content with issues
                    let popupContent = `<strong>Segment ${segment.objid}</strong><br>`;
                    popupContent += `Lengde: ${segment.length_km.toFixed(2)} km<br><br>`;

                    if (issues.length > 0) {
                        popupContent += `<strong>Problemer:</strong><br>`;
                        issues.forEach(issue => {
                            const icon = issue.severity === 'ERROR' ? '🔴' : issue.severity === 'WARNING' ? '⚠️' : 'ℹ️';
                            popupContent += `${icon} ${issue.message}<br>`;
                            if (issue.distance_meters) {
                                popupContent += `&nbsp;&nbsp;Avstand: ${issue.distance_meters.toFixed(2)} m<br>`;
                            }
                            if (issue.overlap_length_meters) {
                                popupContent += `&nbsp;&nbsp;Overlapp: ${issue.overlap_length_meters.toFixed(2)} m<br>`;
                            }
                        });
                    } else {
                        popupContent += '✓ Ingen problemer';
                    }

                    geoJsonLayer.bindPopup(popupContent);
                    geoJsonLayer.addTo(this.debugLayerGroup);
                } catch (error) {
                    console.error(`Error displaying debug segment ${segment.objid}:`, error);
                }
            }
        });

        // Draw connection lines between segments
        // Only show disconnected connections that are actually problematic
        // Focus on sequential connections that are disconnected (these are the real issues)
        console.log(`Total connections received: ${connections.length}`);
        const disconnected = connections.filter(c => {
            const matches = !c.is_connected &&
                c.connection_type === 'sequential' &&
                c.distance_meters > 10.0;
            if (matches) {
                console.log(`Found disconnected sequential connection: ${c.segment1_objid} → ${c.segment2_objid}, distance: ${c.distance_meters}m`);
            }
            return matches;
        });
        console.log(`Filtered disconnected connections (>10m): ${disconnected.length}`);

        // Draw disconnected connections (red/purple)
        disconnected.forEach(conn => {
            const point1 = conn.end_point || conn.point1;
            const point2 = conn.start_point || conn.point2;

            if (point1 && point2) {
                const coords1 = point1.coordinates;
                const coords2 = point2.coordinates;

                // Determine color based on connection type
                let color = '#e74c3c'; // Red for disconnected
                let weight = 4;
                let opacity = 0.9;

                if (conn.connection_type === 'sequential') {
                    color = '#9b59b6'; // Purple for sequential order issues
                    weight = 3;
                    opacity = 0.7;
                }

                const connectionLine = L.polyline([
                    [coords1[1], coords1[0]],
                    [coords2[1], coords2[0]]
                ], {
                    color: color,
                    weight: weight,
                    opacity: opacity,
                    dashArray: '10, 5'
                });

                const connTypeLabel = {
                    'end_to_start': 'Slutt → Start',
                    'end_to_end': 'Slutt → Slutt',
                    'start_to_start': 'Start → Start',
                    'start_to_end': 'Start → Slutt',
                    'sequential': 'Sekvensiell rekkefølge'
                }[conn.connection_type] || 'Ukjent';

                connectionLine.bindPopup(`
                    <strong>🔴 IKKE KOBLET!</strong><br>
                    Segment ${conn.segment1_objid} → ${conn.segment2_objid}<br>
                    Type: ${connTypeLabel}<br>
                    Avstand: ${conn.distance_meters.toFixed(2)} m
                `);

                connectionLine.addTo(this.connectionLayerGroup);

                // Add markers at connection points
                const connTypeParts = connTypeLabel.split('→');
                const label1 = connTypeParts[0] ? connTypeParts[0].trim() : 'Start';
                const label2 = connTypeParts[1] ? connTypeParts[1].trim() : 'Slutt';

                const marker1 = L.circleMarker([coords1[1], coords1[0]], {
                    radius: 8,
                    color: '#e74c3c',
                    fillColor: '#e74c3c',
                    fillOpacity: 0.9,
                    weight: 2
                }).bindPopup(`Segment ${conn.segment1_objid} (${label1})`);

                const marker2 = L.circleMarker([coords2[1], coords2[0]], {
                    radius: 8,
                    color: '#3498db',
                    fillColor: '#3498db',
                    fillOpacity: 0.9,
                    weight: 2
                }).bindPopup(`Segment ${conn.segment2_objid} (${label2})`);

                marker1.addTo(this.connectionLayerGroup);
                marker2.addTo(this.connectionLayerGroup);
            }
        });

        // Add the layer groups to the map
        this.debugLayerGroup.addTo(this.map);

        // Only add connection layer group if it has content
        const disconnectedCount = disconnected.length;
        if (disconnectedCount > 0) {
            this.connectionLayerGroup.addTo(this.map);
        }

        // Add to layers control
        const issueCount = segments.reduce((sum, seg) => sum + (seg.issues?.length || 0), 0);

        this.layerControl.addOverlay(this.debugLayerGroup, `Debugging - Segmenter (${issueCount} problemer)`);
        if (disconnectedCount > 0) {
            this.layerControl.addOverlay(this.connectionLayerGroup, `Debugging - Løse ender (${disconnectedCount} problemer)`);
        }

        console.log(`Debug layers added: ${segments.length} segments, ${disconnectedCount} disconnected sequential connections`);
        if (disconnectedCount === 0) {
            console.log('No disconnected connections found - all segments appear to be connected!');
        }
    }
}

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DebugViewer;
}

