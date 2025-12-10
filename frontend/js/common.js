/**
 * Common utilities and functions shared between route viewer and debug viewer
 */

// Configuration
const CommonConfig = {
    // Use relative paths - works when frontend and backend are on same domain/port
    // Can be overridden with window.BACKEND_URL or localStorage 'backend_url'
    getBackendUrl: function() {
        return window.BACKEND_URL ||
               localStorage.getItem('backend_url') ||
               ''; // Empty string = relative path
    }
};

/**
 * Initialize a Leaflet map with OSM tiles
 * @param {string} mapId - ID of the map container element
 * @param {Array} center - [lat, lng] center coordinates
 * @param {number} zoom - Initial zoom level
 * @returns {L.Map} Leaflet map instance
 */
function initMap(mapId, center = [61.5, 8.5], zoom = 7) {
    const map = L.map(mapId).setView(center, zoom);

    const osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    return map;
}

/**
 * Make an API request to the backend
 * @param {string} endpoint - API endpoint (e.g., '/api/v1/routes/bre10')
 * @returns {Promise<Response>} Fetch response
 */
async function apiRequest(endpoint) {
    const backendUrl = CommonConfig.getBackendUrl();
    const url = backendUrl ? `${backendUrl}${endpoint}` : endpoint;
    console.log(`API request: ${url}`);
    return fetch(url);
}

/**
 * Search for routes
 * @param {Object} params - Search parameters {prefix, name, organization, limit}
 * @returns {Promise<Object>} Search results
 */
async function searchRoutes(params = {}) {
    const queryParams = new URLSearchParams();
    if (params.prefix) queryParams.append('prefix', params.prefix);
    if (params.name) queryParams.append('name', params.name);
    if (params.organization) queryParams.append('organization', params.organization);
    if (params.limit) queryParams.append('limit', params.limit);

    const queryString = queryParams.toString();
    const endpoint = `/api/v1/routes${queryString ? `?${queryString}` : ''}`;

    const response = await apiRequest(endpoint);
    if (!response.ok) {
        throw new Error(`Search failed: ${response.statusText}`);
    }
    return response.json();
}

/**
 * Load route data
 * @param {string} rutenummer - Route identifier
 * @returns {Promise<Object>} Route data
 */
async function loadRouteData(rutenummer) {
    const response = await apiRequest(`/api/v1/routes/${rutenummer}`);
    if (!response.ok) {
        const errorText = await response.text();
        let errorMessage = `Rute ikke funnet: ${response.statusText}`;
        try {
            const errorJson = JSON.parse(errorText);
            errorMessage = errorJson.detail || errorMessage;
        } catch (e) {
            // Ignore JSON parse errors
        }
        throw new Error(errorMessage);
    }
    return response.json();
}

/**
 * Load route segments
 * @param {string} rutenummer - Route identifier
 * @returns {Promise<Object>} Segments data
 */
async function loadRouteSegmentsData(rutenummer) {
    const response = await apiRequest(`/api/v1/routes/${rutenummer}/segments`);
    if (!response.ok) {
        throw new Error(`Failed to load segments: ${response.statusText}`);
    }
    return response.json();
}

/**
 * Load route debug information
 * @param {string} rutenummer - Route identifier
 * @returns {Promise<Object>} Debug data
 */
async function loadRouteDebugData(rutenummer) {
    const response = await apiRequest(`/api/v1/routes/${rutenummer}/debug`);
    if (!response.ok) {
        throw new Error(`Failed to load debug info: ${response.statusText}`);
    }
    return response.json();
}

/**
 * Display a route geometry on the map
 * @param {L.Map} map - Leaflet map instance
 * @param {Object} geometry - GeoJSON geometry
 * @param {Object} style - Leaflet style options
 * @returns {L.GeoJSON} GeoJSON layer
 */
function displayRouteGeometry(map, geometry, style = {}) {
    const defaultStyle = {
        color: '#2c3e50',
        weight: 5,
        opacity: 0.8
    };

    const geoJsonLayer = L.geoJSON(geometry, {
        style: { ...defaultStyle, ...style }
    });

    geoJsonLayer.addTo(map);
    return geoJsonLayer;
}

/**
 * Create a GeoJSON layer with popup and add to a layer group
 * Common helper function to reduce duplication
 * @param {Object} geometry - GeoJSON geometry object
 * @param {Object} options - Configuration options
 * @param {Object} options.style - Leaflet style options (color, weight, opacity)
 * @param {string} options.popupContent - HTML content for popup (optional)
 * @param {L.LayerGroup} options.layerGroup - Layer group to add the layer to (optional)
 * @param {string} options.layerName - Name for error messages (optional)
 * @returns {L.GeoJSON|null} GeoJSON layer or null if creation failed
 */
function createGeoJSONLayer(geometry, options = {}) {
    if (!geometry || !geometry.coordinates) {
        return null;
    }

    const {
        style = {},
        popupContent = null,
        layerGroup = null,
        layerName = 'layer'
    } = options;

    try {
        const geoJsonLayer = L.geoJSON(geometry, {
            style: style
        });

        // Add popup if content provided
        if (popupContent) {
            geoJsonLayer.bindPopup(popupContent);
        }

        // Add to layer group if provided
        if (layerGroup) {
            geoJsonLayer.addTo(layerGroup);
        }

        return geoJsonLayer;
    } catch (error) {
        console.error(`Error creating GeoJSON layer for ${layerName}:`, error);
        return null;
    }
}

/**
 * Get color for a property based on its matrikkelenhet
 * @param {string} matrikkelenhet - Property identifier
 * @param {Array} colors - Color palette
 * @returns {string} Hex color code
 */
function getColorForProperty(matrikkelenhet, colors = null) {
    if (!colors) {
        colors = PROPERTY_COLORS; // Use shared constant
    }

    // Simple hash function to get consistent color for same matrikkelenhet
    let hash = 0;
    for (let i = 0; i < matrikkelenhet.length; i++) {
        hash = matrikkelenhet.charCodeAt(i) + ((hash << 5) - hash);
    }
    return colors[Math.abs(hash) % colors.length];
}

/**
 * Safely get bounds from a Leaflet layer
 * @param {L.Layer} layer - Leaflet layer (GeoJSON, LayerGroup, etc.)
 * @param {string} layerName - Name of layer for error messages (optional)
 * @returns {L.LatLngBounds|null} Bounds if valid, null otherwise
 */
function getBoundsFromLayer(layer, layerName = 'layer') {
    if (!layer) {
        return null;
    }

    if (typeof layer.getBounds !== 'function') {
        return null;
    }

    // Check if it's a layer group with layers
    if (layer.getLayers && typeof layer.getLayers === 'function') {
        const layers = layer.getLayers();
        if (layers.length === 0) {
            return null;
        }
    }

    try {
        const bounds = layer.getBounds();
        if (bounds && isValidBounds(bounds)) {
            return bounds;
        }
    } catch (error) {
        console.warn(`Could not get bounds from ${layerName}:`, error);
    }
    return null;
}

/**
 * Check if bounds are valid
 * Validates Leaflet bounds by checking if they have valid coordinates
 * @param {L.LatLngBounds} bounds - Leaflet bounds object
 * @returns {boolean} True if bounds are valid
 */
function isValidBounds(bounds) {
    if (!bounds) {
        return false;
    }

    try {
        // First, try Leaflet's built-in isValid() method if available
        // Leaflet LatLngBounds has isValid() method in most versions
        if (typeof bounds.isValid === 'function') {
            try {
                const isValid = bounds.isValid();
                // If Leaflet says it's valid, trust it (but we could add additional checks)
                return isValid;
            } catch (e) {
                // If isValid() throws an error, fall through to manual validation
                console.warn('Leaflet bounds.isValid() threw an error, using manual validation:', e);
            }
        }

        // Manual validation as fallback (for older Leaflet versions or edge cases)
        // Check if bounds has the required methods
        if (typeof bounds.getSouthWest !== 'function' || typeof bounds.getNorthEast !== 'function') {
            return false;
        }

        // Get the corner points
        const sw = bounds.getSouthWest();
        const ne = bounds.getNorthEast();

        // Check if corner points are valid
        if (!sw || !ne) {
            return false;
        }

        // Check if coordinates are valid numbers
        if (typeof sw.lat !== 'number' || typeof sw.lng !== 'number' ||
            typeof ne.lat !== 'number' || typeof ne.lng !== 'number') {
            return false;
        }

        // Check if coordinates are within valid ranges
        if (isNaN(sw.lat) || isNaN(sw.lng) || isNaN(ne.lat) || isNaN(ne.lng)) {
            return false;
        }

        // Check if bounds are logically valid (south < north, etc.)
        // Note: For wrapped bounds, west might be > east, so we don't check that
        if (sw.lat > ne.lat) {
            return false;
        }

        // Manual validation passed
        return true;
    } catch (e) {
        // If any error occurs during validation, bounds are invalid
        return false;
    }
}

/**
 * Safely fit map to bounds with error handling
 * @param {L.Map} map - Leaflet map instance
 * @param {L.LatLngBounds} bounds - Bounds to fit
 * @param {Object} options - Options for fitBounds (padding, maxZoom, etc.)
 * @returns {boolean} True if successfully fitted, false otherwise
 */
function fitMapToBounds(map, bounds, options = {}) {
    if (!map || !bounds) {
        return false;
    }

    if (!isValidBounds(bounds)) {
        return false;
    }

    try {
        const defaultOptions = { padding: [50, 50] };
        map.fitBounds(bounds, { ...defaultOptions, ...options });
        return true;
    } catch (error) {
        console.warn('Could not fit bounds to map:', error);
        return false;
    }
}

/**
 * Combine multiple bounds into a single bounds object
 * @param {Array<L.LatLngBounds>} boundsArray - Array of bounds to combine
 * @returns {L.LatLngBounds|null} Combined bounds, or null if no valid bounds
 */
function combineBounds(boundsArray) {
    if (!boundsArray || boundsArray.length === 0) {
        return null;
    }

    const validBounds = boundsArray.filter(b => isValidBounds(b));
    if (validBounds.length === 0) {
        return null;
    }

    const combined = L.latLngBounds([]);
    validBounds.forEach(bounds => {
        combined.extend(bounds.getSouthWest());
        combined.extend(bounds.getNorthEast());
    });

    return isValidBounds(combined) ? combined : null;
}

/**
 * Get bounds from GeoJSON geometry
 * @param {Object} geometry - GeoJSON geometry object
 * @returns {L.LatLngBounds|null} Bounds if valid, null otherwise
 */
function getBoundsFromGeometry(geometry) {
    if (!geometry || !geometry.coordinates) {
        return null;
    }

    try {
        const bounds = L.latLngBounds([]);
        let hasCoords = false;

        const processCoordinates = (coords) => {
            if (Array.isArray(coords[0]) && Array.isArray(coords[0][0])) {
                // MultiLineString or Polygon
                coords.forEach(coordArray => processCoordinates(coordArray));
            } else if (Array.isArray(coords[0]) && typeof coords[0][0] === 'number') {
                // LineString or Polygon ring
                coords.forEach(coord => {
                    if (coord.length >= 2) {
                        bounds.extend([coord[1], coord[0]]); // [lat, lng]
                        hasCoords = true;
                    }
                });
            } else if (coords.length >= 2 && typeof coords[0] === 'number') {
                // Point
                bounds.extend([coords[1], coords[0]]); // [lat, lng]
                hasCoords = true;
            }
        };

        processCoordinates(geometry.coordinates);
        return hasCoords && isValidBounds(bounds) ? bounds : null;
    } catch (error) {
        console.warn('Could not get bounds from geometry:', error);
        return null;
    }
}

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        CommonConfig,
        initMap,
        apiRequest,
        searchRoutes,
        loadRouteData,
        loadRouteSegmentsData,
        loadRouteDebugData,
        displayRouteGeometry,
        createGeoJSONLayer,
        getColorForProperty,
        getBoundsFromLayer,
        isValidBounds,
        fitMapToBounds,
        combineBounds,
        getBoundsFromGeometry
    };
}

