/** Main App component */
import { useState, useEffect } from 'react';
import { MapView } from './components/MapView';
import { SidePanel } from './components/SidePanel';
import { RouteSelector } from './components/RouteSelector';
import { NotificationContainer } from './components/NotificationContainer';
import { api } from './api/client';
import { handleApiError } from './utils/errorHandler';
import { notificationManager } from './utils/notifications';
import type { Changeset, LocalEvent, RouteResponse } from './types';
import './App.css';

function App() {
  const [changeset, setChangeset] = useState<Changeset | null>(null);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);

  const [routeNumber, setRouteNumber] = useState<string | null>(null);
  const [selectedRouteNumber, setSelectedRouteNumber] = useState<string | null>(null);
  const [showRouteSelector, setShowRouteSelector] = useState(true);
  const [routeGeometry, setRouteGeometry] = useState<GeoJSON.Geometry | null>(null);

  // Local changes (before changeset is created)
  const [localEvents, setLocalEvents] = useState<LocalEvent[]>([]);

  // Get changeset ID or route number from URL
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const changesetId = urlParams.get('changeset');
    const route = urlParams.get('route');

    if (route) {
      setRouteNumber(route);
      setShowRouteSelector(false);
      // Load route geometry
      fetch(`/api/v1/routes/${route}?include_geometry=true`)
        .then(res => res.json())
        .then((data: RouteResponse) => setRouteGeometry(data.route_geometry || null))
        .catch((error) => {
          const appError = handleApiError(error, 'Route Geometry Load');
          notificationManager.error(`Kunne ikke laste rutegeometri: ${appError.message}`);
        });
    }

    if (changesetId) {
      api.getChangeset(changesetId)
        .then(setChangeset)
        .catch((error) => {
          const appError = handleApiError(error, 'Changeset Load');
          notificationManager.error(`Kunne ikke laste changeset: ${appError.message}`);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const handleSelectRoute = async (rutenummer: string) => {
    if (!rutenummer) return;

    setSelectedRouteNumber(rutenummer);
    setLoading(true);
    try {
      // Load route geometry and display on map
      const routeResponse = await fetch(`/api/v1/routes/${rutenummer}?include_geometry=true`);
      if (!routeResponse.ok) {
        throw new Error(`Failed to load route: ${routeResponse.statusText}`);
      }
      const routeData = await routeResponse.json() as RouteResponse;
      setRouteGeometry(routeData.route_geometry || null);
      setRouteNumber(rutenummer);
      setShowRouteSelector(false);
      // Update URL (without changeset yet)
      window.history.replaceState({}, '', `?route=${rutenummer}`);
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Route Load');
      notificationManager.error(`Kunne ikke laste rute: ${appError.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Add local event (before changeset is created)
  const handleLocalEventAdded = (event: LocalEvent) => {
    setLocalEvents(prev => [...prev, event]);
  };

  // Save/Commit: Create changeset and send all local events
  const handleSaveChanges = async () => {
    if (!routeNumber || localEvents.length === 0) {
      notificationManager.warning('Ingen endringer å lagre');
      return;
    }

    setLoading(true);
    try {
      // Create changeset
      const newChangeset = await api.createChangeset({
        title: `Redigering: ${routeNumber}`,
        description: `Endringer for rute ${routeNumber}`,
        base_snapshot: 'default',
      });

      // Send all local events to changeset
      for (const event of localEvents) {
        await api.addEvent(newChangeset.id, event);
      }

      setChangeset(newChangeset);
      setLocalEvents([]); // Clear local events

      // Update URL with changeset
      window.history.replaceState({}, '', `?route=${routeNumber}&changeset=${newChangeset.id}`);

      notificationManager.success(`Endringer lagret! ${localEvents.length} endringer sendt til changeset.`);
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Save Changes');
      notificationManager.error(`Kunne ikke lagre endringer: ${appError.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleEventAdded = () => {
    // Reload changeset to get updated data
    if (changeset) {
      api.getChangeset(changeset.id)
        .then(setChangeset)
        .catch((error) => {
          const appError = handleApiError(error, 'Reload Changeset');
          notificationManager.error(`Kunne ikke oppdatere changeset: ${appError.message}`);
        });
    }
  };

  const handleChangesetUpdate = () => {
    if (changeset) {
      api.getChangeset(changeset.id)
        .then(setChangeset)
        .catch((error) => {
          const appError = handleApiError(error, 'Update Changeset');
          notificationManager.error(`Kunne ikke oppdatere changeset: ${appError.message}`);
        });
    }
  };

  return (
    <>
      <NotificationContainer />
      <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden' }}>
      {/* Sidebar */}
      <div style={{
        width: '400px',
        backgroundColor: '#f8f9fa',
        borderRight: '1px solid #dee2e6',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}>
        <div style={{
          padding: '1rem',
          borderBottom: '1px solid #dee2e6',
          backgroundColor: 'white',
        }}>
          <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600 }}>
            {changeset ? `Redigering: ${routeNumber || 'Rute'}` : 'Velg en rute'}
          </h2>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '1rem' }}>
          {showRouteSelector ? (
            <RouteSelector onSelectRoute={handleSelectRoute} loading={loading} />
          ) : changeset ? (
            <SidePanel
              changeset={changeset}
              selectedFeatureId={selectedFeatureId}
              onChangesetUpdate={handleChangesetUpdate}
            />
          ) : routeNumber ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <h3 style={{ margin: '0 0 8px 0' }}>Rute: {routeNumber}</h3>
                <p style={{ color: '#666', margin: '0 0 16px 0' }}>
                  Ruten er valgt og vises på kartet. Gjør endringer på kartet eller i listen nedenfor.
                </p>

                {/* Show pending changes count and Save button */}
                {localEvents.length > 0 && (
                  <div style={{
                    padding: '12px',
                    backgroundColor: '#fff3cd',
                    borderRadius: '4px',
                    marginBottom: '16px',
                    border: '1px solid #ffc107',
                  }}>
                    <div style={{ marginBottom: '8px' }}>
                      <strong>Ulagrede endringer: {localEvents.length}</strong>
                    </div>
                    <button
                      onClick={handleSaveChanges}
                      disabled={loading}
                      style={{
                        padding: '8px 16px',
                        fontSize: '14px',
                        backgroundColor: '#28a745',
                        color: 'white',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: loading ? 'not-allowed' : 'pointer',
                        fontWeight: 'bold',
                        width: '100%',
                      }}
                    >
                      {loading ? 'Lagrer...' : '💾 Lagre endringer'}
                    </button>
                  </div>
                )}

                <p style={{ marginTop: '12px', fontSize: '12px', color: '#666', fontStyle: 'italic' }}>
                  Bruk verktøyene på venstre side av kartet for å gjøre endringer.
                </p>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {/* Map Container */}
      <div style={{ flex: 1, position: 'relative' }}>
        <MapView
          changeset={changeset}
          routeGeometry={routeGeometry}
          routeNumber={routeNumber}
          selectedRouteNumber={selectedRouteNumber}
          onRouteSelect={handleSelectRoute}
          onEventAdded={changeset ? handleEventAdded : handleLocalEventAdded}
          selectedFeatureId={selectedFeatureId}
          onFeatureSelect={setSelectedFeatureId}
          localEventsCount={localEvents.length}
        />
      </div>
    </div>
    </>
  );
}

export default App;
