/**
 * Test setup file - runs before all tests
 */
import React from 'react';
import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// Cleanup after each test
afterEach(() => {
  cleanup();
});

// Mock window.matchMedia (used by some UI libraries)
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock ResizeObserver (used by Leaflet)
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

// Mock IntersectionObserver
global.IntersectionObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

// Mock Leaflet (basic mocks - extend as needed)
vi.mock('leaflet', () => {
  const mockMap = {
    setView: vi.fn().mockReturnThis(),
    on: vi.fn(),
    off: vi.fn(),
    getBounds: vi.fn().mockReturnValue({
      getWest: () => -180,
      getEast: () => 180,
      getNorth: () => 90,
      getSouth: () => -90,
    }),
    getContainer: vi.fn().mockReturnValue(document.createElement('div')),
    removeLayer: vi.fn(),
    addLayer: vi.fn(),
    fitBounds: vi.fn(),
    closePopup: vi.fn(),
  };

  return {
    default: {
      map: vi.fn().mockReturnValue(mockMap),
      tileLayer: vi.fn().mockReturnValue({
        addTo: vi.fn().mockReturnThis(),
      }),
      geoJSON: vi.fn().mockReturnValue({
        addTo: vi.fn().mockReturnThis(),
        bindPopup: vi.fn().mockReturnThis(),
        getBounds: vi.fn().mockReturnValue({
          isValid: () => true,
        }),
        on: vi.fn(),
        off: vi.fn(),
        setStyle: vi.fn(),
        eachLayer: vi.fn(),
        clearLayers: vi.fn(),
      }),
      layerGroup: vi.fn().mockReturnValue({
        addTo: vi.fn().mockReturnThis(),
        addLayer: vi.fn(),
        removeLayer: vi.fn(),
        clearLayers: vi.fn(),
        eachLayer: vi.fn(),
        getLayers: vi.fn().mockReturnValue([]),
      }),
      marker: vi.fn().mockReturnValue({
        addTo: vi.fn().mockReturnThis(),
        setLatLng: vi.fn(),
        bindPopup: vi.fn().mockReturnThis(),
      }),
      circleMarker: vi.fn().mockReturnValue({
        addTo: vi.fn().mockReturnThis(),
      }),
      control: {
        layers: vi.fn().mockReturnValue({
          addTo: vi.fn().mockReturnThis(),
          addOverlay: vi.fn(),
          removeLayer: vi.fn(),
        }),
      },
      icon: vi.fn().mockReturnValue({}),
      divIcon: vi.fn().mockReturnValue({}),
    },
  };
});

// Mock react-leaflet
vi.mock('react-leaflet', async () => {
  const actual = await vi.importActual('react-leaflet');
  return {
    ...actual,
    MapContainer: ({ children }: { children: React.ReactNode }) =>
      React.createElement('div', { 'data-testid': 'map-container' }, children),
    TileLayer: () => React.createElement('div', { 'data-testid': 'tile-layer' }),
    LayersControl: Object.assign(
      ({ children }: { children: React.ReactNode }) =>
        React.createElement('div', { 'data-testid': 'layers-control' }, children),
      {
        BaseLayer: ({ children, name }: { children: React.ReactNode; name: string }) =>
          React.createElement('div', { 'data-testid': `base-layer-${name}` }, children),
      }
    ),
    GeoJSON: () => React.createElement('div', { 'data-testid': 'geojson-layer' }),
    useMap: () => ({
      setView: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
      getBounds: vi.fn().mockReturnValue({
        getWest: () => -180,
        getEast: () => 180,
        getNorth: () => 90,
        getSouth: () => -90,
      }),
      getContainer: vi.fn().mockReturnValue(document.createElement('div')),
    }),
  };
});
