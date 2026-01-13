/**
 * Header component with Stiflyt branding, navigation, and route search
 */
import { useState, useEffect } from 'react';
import './Header.css';

interface Route {
  rutenummer: string;
  rutenavn?: string | null;
  vedlikeholdsansvarlig?: string | null;
  type?: string;
}

interface HeaderProps {
  onSelectRoute: (rutenummer: string) => void;
  selectedRouteNumber?: string | null;
  loading?: boolean;
}

export function Header({ onSelectRoute, selectedRouteNumber, loading = false }: HeaderProps) {
  const [searchQuery, setSearchQuery] = useState(selectedRouteNumber || '');
  const [routes, setRoutes] = useState<Route[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showResults, setShowResults] = useState(false);

  // Update search query when selected route changes
  useEffect(() => {
    if (selectedRouteNumber) {
      setSearchQuery(selectedRouteNumber);
    }
  }, [selectedRouteNumber]);

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
      // If empty query, don't search
      if (queryTrimmed.length === 0) {
        setRoutes([]);
        setShowResults(false);
        return;
      }

      // If query is short (1-2 chars), treat as prefix search
      if (queryTrimmed.length <= 2) {
        const response = await fetch(`/api/v1/routes?prefix=${encodeURIComponent(queryTrimmed)}&limit=200`);
        if (response.ok) {
          const data = await response.json();
          setRoutes(data.routes || []);
          setShowResults(true);
        } else {
          setRoutes([]);
          setShowResults(false);
        }
        return;
      }

      // For longer queries, try exact match first via search places, then prefix search
      try {
        const data = await searchPlaces(queryTrimmed, 20);
        const exactRoutes = (data.results || []).filter((r: Route) => r.type === 'rute');
        
        if (exactRoutes.length > 0) {
          setRoutes(exactRoutes);
          setShowResults(true);
        } else {
          // If no exact match, try prefix search
          const response = await fetch(`/api/v1/routes?prefix=${encodeURIComponent(queryTrimmed)}&limit=200`);
          if (response.ok) {
            const routeData = await response.json();
            setRoutes(routeData.routes || []);
            setShowResults(true);
          } else {
            setRoutes([]);
            setShowResults(false);
          }
        }
      } catch (error) {
        // Silently handle search errors
        setRoutes([]);
        setShowResults(false);
      }
    } catch (error) {
      // Silently handle search errors
      setRoutes([]);
      setShowResults(false);
    } finally {
      setIsSearching(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      performRouteSearch(searchQuery);
    }, 300); // Debounce search

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery]);

  const handleRouteSelect = (rutenummer: string) => {
    setSearchQuery(rutenummer);
    setShowResults(false);
    onSelectRoute(rutenummer);
  };

  // Close results when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (!target.closest('.header-search-container')) {
        setShowResults(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <header className="app-header">
      <div className="header-left">
        <h1>
          <img src="/images/stiflyt.png" alt="Stiflyt Logo" className="header-logo" />
          Changeset Editor
        </h1>
        <nav className="main-nav">
          <a href="/routes.html" className="nav-link">Rutevalidering</a>
          <a href="#" className="nav-link" onClick={(e) => {
            e.preventDefault();
            alert('Om Changeset Editor\n\nEt verktøy for å redigere rutesegmenter med event sourcing, validering og GitHub PR-integrasjon.');
          }}>Om</a>
        </nav>
      </div>
      <div className="header-controls">
        <div className="header-search-container">
          <input
            type="text"
            className="header-search-input"
            placeholder="Søk etter rute (f.eks. BRE017)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onFocus={() => {
              if (routes.length > 0) {
                setShowResults(true);
              }
            }}
            disabled={loading}
            aria-label="Søk etter rute"
          />
          {isSearching && (
            <span className="header-search-spinner">⏳</span>
          )}
          {showResults && routes.length > 0 && (
            <div className="header-search-results">
              {routes.map((route) => (
                <div
                  key={route.rutenummer}
                  className="header-search-result-item"
                  onClick={() => handleRouteSelect(route.rutenummer)}
                >
                  <div className="header-search-result-title">{route.rutenummer}</div>
                  {route.rutenavn && (
                    <div className="header-search-result-subtitle">{route.rutenavn}</div>
                  )}
                  {route.vedlikeholdsansvarlig && (
                    <div className="header-search-result-meta">{route.vedlikeholdsansvarlig}</div>
                  )}
                </div>
              ))}
            </div>
          )}
          {showResults && searchQuery.length >= 2 && routes.length === 0 && !isSearching && (
            <div className="header-search-results">
              <div className="header-search-result-item header-search-no-results">
                Ingen ruter funnet
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
