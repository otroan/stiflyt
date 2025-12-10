/**
 * Shared constants for route visualization
 */

// Main color palette for properties (15 colors)
const PROPERTY_COLORS = [
    '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
    '#1abc9c', '#e67e22', '#34495e', '#16a085', '#27ae60',
    '#2980b9', '#8e44ad', '#c0392b', '#d35400', '#7f8c8d'
];

// Color palette for route components (8 colors)
const COMPONENT_COLORS = [
    '#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6',
    '#1abc9c', '#e67e22', '#34495e'
];

// Extended color palette for segments (20 colors)
const SEGMENT_COLORS = [
    '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
    '#1abc9c', '#e67e22', '#34495e', '#16a085', '#27ae60',
    '#2980b9', '#8e44ad', '#c0392b', '#d35400', '#7f8c8d',
    '#e91e63', '#00bcd4', '#4caf50', '#ff9800', '#673ab7'
];

// Make available globally (for browser script tags)
if (typeof window !== 'undefined') {
    window.PROPERTY_COLORS = PROPERTY_COLORS;
    window.COMPONENT_COLORS = COMPONENT_COLORS;
    window.SEGMENT_COLORS = SEGMENT_COLORS;
}

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        PROPERTY_COLORS,
        COMPONENT_COLORS,
        SEGMENT_COLORS
    };
}
