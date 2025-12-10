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
 * Get color for a property based on its matrikkelenhet
 * @param {string} matrikkelenhet - Property identifier
 * @param {Array} colors - Color palette
 * @returns {string} Hex color code
 */
function getColorForProperty(matrikkelenhet, colors = null) {
    if (!colors) {
        colors = [
            '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
            '#1abc9c', '#e67e22', '#34495e', '#16a085', '#27ae60',
            '#2980b9', '#8e44ad', '#c0392b', '#d35400', '#7f8c8d'
        ];
    }

    // Simple hash function to get consistent color for same matrikkelenhet
    let hash = 0;
    for (let i = 0; i < matrikkelenhet.length; i++) {
        hash = matrikkelenhet.charCodeAt(i) + ((hash << 5) - hash);
    }
    return colors[Math.abs(hash) % colors.length];
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
        getColorForProperty
    };
}

