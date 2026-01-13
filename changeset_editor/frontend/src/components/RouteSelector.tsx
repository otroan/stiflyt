/** Route selector component for choosing a route to edit */
import { useState, useEffect } from 'react';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';

interface Route {
  rutenummer: string;
  rutenavn?: string;
  vedlikeholdsansvarlig?: string;
  type?: string; // For search/places results
}

interface RouteSelectorProps {
  onSelectRoute: (rutenummer: string) => void;
  loading: boolean;
}

export function RouteSelector({ onSelectRoute, loading }: RouteSelectorProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [routes, setRoutes] = useState<Route[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const searchPlaces = async (query: string, limit: number = 20): Promise<{ results: Route[] }> => {
    const response = await fetch(`/api/v1/search/places?q=${encodeURIComponent(query)}&limit=${limit}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  };

  const performRouteSearch = async (query: string) => {
    const queryTrimmed = query ? query.trim() : '';

    setIsSearching(true);
    try {
      // If empty query, show all routes
      if (queryTrimmed.length === 0) {
        const response = await fetch(`/api/v1/routes?limit=200`);
        if (response.ok) {
          const data = await response.json();
          setRoutes(data.routes || []);
        } else {
          setRoutes([]);
        }
        return;
      }

      // If query is short (1-2 chars), treat as prefix search
      if (queryTrimmed.length <= 2) {
        const response = await fetch(`/api/v1/routes?prefix=${encodeURIComponent(queryTrimmed)}&limit=200`);
        if (response.ok) {
          const data = await response.json();
          setRoutes(data.routes || []);
        } else {
          setRoutes([]);
        }
        return;
      }

      // For longer queries, try exact match first via search places, then prefix search
      try {
        const data = await searchPlaces(queryTrimmed, 20);
        const exactRoutes = (data.results || []).filter((r: Route) => r.type === 'rute');
        
        if (exactRoutes.length > 0) {
          setRoutes(exactRoutes);
        } else {
          // If no exact match, try prefix search
          const response = await fetch(`/api/v1/routes?prefix=${encodeURIComponent(queryTrimmed)}&limit=200`);
          if (response.ok) {
            const routeData = await response.json();
            setRoutes(routeData.routes || []);
          } else {
            setRoutes([]);
          }
        }
      } catch (error) {
        const appError = handleApiError(error, 'Route Search');
        // Don't show notification for search errors - just log silently
        // notificationManager.warning(`Søk feilet: ${appError.message}`);
        setRoutes([]);
      }
    } catch (error) {
      const appError = handleApiError(error, 'Route Search');
      // Don't show notification for search errors - just log silently
      // notificationManager.warning(`Søk feilet: ${appError.message}`);
      setRoutes([]);
    } finally {
      setIsSearching(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      performRouteSearch(searchQuery);
    }, 300); // Debounce search

    return () => clearTimeout(timer);
  }, [searchQuery]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div>
        <input
          type="text"
          placeholder="Søk etter rute (f.eks. BRE017)"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{
            width: '100%',
            padding: '12px',
            fontSize: '16px',
            border: '1px solid #ccc',
            borderRadius: '4px',
          }}
          disabled={loading}
        />
      </div>

      {isSearching && (
        <div style={{ textAlign: 'center', padding: '20px' }}>Søker...</div>
      )}

      {!isSearching && routes.length > 0 && (
        <div
          style={{
            border: '1px solid #ddd',
            borderRadius: '4px',
            maxHeight: '400px',
            overflowY: 'auto',
          }}
        >
          {routes.map((route) => (
            <div
              key={route.rutenummer}
              onClick={() => {
                onSelectRoute(route.rutenummer);
              }}
              style={{
                padding: '12px',
                borderBottom: '1px solid #eee',
                cursor: 'pointer',
                transition: 'background-color 0.2s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = '#f5f5f5';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'white';
              }}
            >
              <div style={{ fontWeight: 'bold', fontSize: '16px' }}>
                {route.rutenummer}
              </div>
              {route.rutenavn && (
                <div style={{ color: '#666', marginTop: '4px' }}>
                  {route.rutenavn}
                </div>
              )}
              {route.vedlikeholdsansvarlig && (
                <div style={{ color: '#999', fontSize: '12px', marginTop: '4px' }}>
                  {route.vedlikeholdsansvarlig}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!isSearching && searchQuery.length >= 2 && routes.length === 0 && (
        <div style={{ textAlign: 'center', padding: '20px', color: '#666' }}>
          Ingen ruter funnet
        </div>
      )}

      {!isSearching && searchQuery.length === 0 && routes.length === 0 && (
        <div style={{ textAlign: 'center', padding: '20px', color: '#666' }}>
          Skriv for å søke etter ruter, eller la stå tomt for å se alle ruter
        </div>
      )}

      {!isSearching && searchQuery.length === 1 && routes.length === 0 && (
        <div style={{ textAlign: 'center', padding: '20px', color: '#666' }}>
          Søker etter ruter som starter med "{searchQuery}"...
        </div>
      )}
    </div>
  );
}
