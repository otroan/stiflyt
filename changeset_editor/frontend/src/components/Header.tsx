/**
 * Header component with Stiflyt branding, navigation, and route search
 */
import { useState, useEffect, useRef } from 'react';
import { api } from '../api/client';
import './Header.css';

interface Route {
  rutenummer: string;
  rutenavn?: string | null;
  vedlikeholdsansvarlig?: string | null;
  type?: string;
}

interface HeaderProps {
  onSelectRoute: (rutenummer: string | null) => void;
  selectedRouteNumber?: string | null;
  loading?: boolean;
  changeset?: { id: string; status: string } | null;
  localEventsCount?: number;
  onSaveChanges?: () => void;
  onLoadFromFile?: (file: File) => void;
  onPublish?: () => void;
}

export function Header({
  onSelectRoute,
  selectedRouteNumber,
  loading = false,
  changeset,
  localEventsCount = 0,
  onSaveChanges,
  onLoadFromFile,
  onPublish,
}: HeaderProps) {
  const [searchQuery, setSearchQuery] = useState(selectedRouteNumber || '');
  const [routes, setRoutes] = useState<Route[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const searchControllerRef = useRef<AbortController | null>(null);
  const routesLimit = 200; // Default limit for route searches

  // Update search query when selected route changes
  useEffect(() => {
    if (selectedRouteNumber) {
      setSearchQuery(selectedRouteNumber);
    }
  }, [selectedRouteNumber]);

  const searchPlaces = async (query: string, limit: number = 20): Promise<{ results: Route[] }> => {
    return api.searchPlaces(query, limit);
  };

  const performRouteSearch = async (query: string) => {
    const queryTrimmed = query ? query.trim() : '';
    if (searchControllerRef.current) {
      searchControllerRef.current.abort();
    }
    const controller = new AbortController();
    searchControllerRef.current = controller;
    const { signal } = controller;

    setIsSearching(true);
    try {
      // If empty query, show all routes (with reasonable limit)
      if (queryTrimmed.length === 0) {
        try {
          const data = await api.listRoutes({ limit: routesLimit }, { signal });
          if (signal.aborted) return;
          setRoutes(data.routes || []);
          setShowResults(true);
        } catch {
          if (signal.aborted) return;
          setRoutes([]);
          setShowResults(false);
        } finally {
          if (!signal.aborted) {
            setIsSearching(false);
          }
        }
        return;
      }

      // If query is short (1-2 chars), treat as prefix search
      if (queryTrimmed.length <= 2) {
        try {
          const data = await api.listRoutes({ prefix: queryTrimmed, limit: routesLimit }, { signal });
          if (signal.aborted) return;
          setRoutes(data.routes || []);
          setShowResults(true);
        } catch {
          if (signal.aborted) return;
          setRoutes([]);
          setShowResults(false);
        }
        return;
      }

      // For longer queries, try exact match first via search places, then prefix search
      try {
        const data = await searchPlaces(queryTrimmed, 20);
        if (signal.aborted) return;
        const exactRoutes = (data.results || []).filter((r: Route) => r.type === 'rute');
        
        if (exactRoutes.length > 0) {
          setRoutes(exactRoutes);
          setShowResults(true);
        } else {
          // If no exact match, try prefix search
          const routeData = await api.listRoutes({ prefix: queryTrimmed, limit: routesLimit }, { signal });
          if (signal.aborted) return;
          setRoutes(routeData.routes || []);
          setShowResults(true);
        }
      } catch (error) {
        if (signal.aborted) return;
        // Silently handle search errors
        setRoutes([]);
        setShowResults(false);
      }
    } catch (error) {
      if (signal.aborted) return;
      // Silently handle search errors
      setRoutes([]);
      setShowResults(false);
    } finally {
      if (!signal.aborted) {
        setIsSearching(false);
      }
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      performRouteSearch(searchQuery);
    }, 300); // Debounce search

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery]);

  useEffect(() => {
    return () => {
      if (searchControllerRef.current) {
        searchControllerRef.current.abort();
      }
    };
  }, []);

  const handleRouteSelect = (rutenummer: string) => {
    setSearchQuery(rutenummer);
    setShowResults(false);
    onSelectRoute(rutenummer);
  };

  const handleDeselectRoute = () => {
    setSearchQuery('');
    setShowResults(false);
    onSelectRoute(null);
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
        {/* Changeset actions */}
        {(changeset || localEventsCount > 0) && (
          <div className="header-actions" style={{ display: 'flex', gap: '8px', alignItems: 'center', marginRight: '12px' }}>
            {localEventsCount > 0 && (
              <span style={{ fontSize: '0.85rem', color: '#666', marginRight: '4px' }}>
                {localEventsCount} ulagret{localEventsCount !== 1 ? 'e' : ''}
              </span>
            )}
            {onSaveChanges && (changeset || localEventsCount > 0) && (
              <button
                onClick={onSaveChanges}
                disabled={loading}
                className="btn btn-primary"
                style={{ fontSize: '0.9rem', padding: '6px 12px' }}
                title="Eksporter changeset til JSON-fil"
              >
                💾 Lagre til fil
              </button>
            )}
            {onPublish && localEventsCount > 0 && !changeset && (
              <button
                onClick={onPublish}
                disabled={loading}
                className="btn btn-success"
                style={{ fontSize: '0.9rem', padding: '6px 12px' }}
                title="Opprett changeset og send til backend"
              >
                {loading ? 'Publiserer...' : '📤 Publiser'}
              </button>
            )}
            {onLoadFromFile && (
              <>
                <label
                  htmlFor="header-file-import"
                  className="btn btn-secondary"
                  style={{
                    fontSize: '0.9rem',
                    padding: '6px 12px',
                    cursor: 'pointer',
                    margin: 0,
                  }}
                  title="Importer changeset fra JSON-fil"
                >
                  📂 Importer
                </label>
                <input
                  id="header-file-import"
                  type="file"
                  accept=".json"
                  style={{ display: 'none' }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file && onLoadFromFile) {
                      onLoadFromFile(file);
                    }
                    // Reset input
                    e.target.value = '';
                  }}
                />
              </>
            )}
          </div>
        )}

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
          {selectedRouteNumber && (
            <button
              type="button"
              className="btn btn-secondary"
              style={{ marginLeft: '8px', padding: '6px 10px' }}
              onClick={handleDeselectRoute}
              disabled={loading}
              title="Fjern valgt rute"
            >
              ✕
            </button>
          )}
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
