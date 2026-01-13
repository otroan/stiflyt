/** Main App component */
import { useState, useEffect } from 'react';
import { MapView } from './components/MapView';
import { Header } from './components/Header';
import { InfoPanel } from './components/InfoPanel';
import { NotificationContainer } from './components/NotificationContainer';
import { api } from './api/client';
import { handleApiError } from './utils/errorHandler';
import { notificationManager } from './utils/notifications';
import type { Changeset, LocalEvent, RouteResponse } from './types';
import './App.css';

function App() {
  const [changeset, setChangeset] = useState<Changeset | null>(null);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | undefined>();
  const [selectedFeatureProperties, setSelectedFeatureProperties] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  const [routeNumber, setRouteNumber] = useState<string | null>(null);
  const [selectedRouteNumber, setSelectedRouteNumber] = useState<string | null>(null);
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
      setSelectedRouteNumber(route);
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
      setSelectedRouteNumber(rutenummer);
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
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw', overflow: 'hidden' }}>
        {/* Header - Fixed at top */}
        <Header
          onSelectRoute={handleSelectRoute}
          selectedRouteNumber={selectedRouteNumber}
          loading={loading}
        />

        {/* Main Content Area - Below header */}
        <div style={{
          display: 'flex',
          flex: 1,
          marginTop: '60px', // Header height (fixed header)
          position: 'relative',
          overflow: 'hidden',
          height: 'calc(100vh - 60px)' // Full height minus header
        }}>
          {/* Map Container - Full Width */}
          <div style={{ flex: 1, position: 'relative', width: '100%', height: '100%' }}>
          <MapView
            changeset={changeset}
            routeGeometry={routeGeometry}
            routeNumber={routeNumber}
            selectedRouteNumber={selectedRouteNumber}
            onRouteSelect={handleSelectRoute}
            onEventAdded={changeset ? handleEventAdded : handleLocalEventAdded}
            selectedFeatureId={selectedFeatureId}
            onFeatureSelect={(id, properties) => {
              setSelectedFeatureId(id);
              setSelectedFeatureProperties(properties || null);
            }}
            localEventsCount={localEvents.length}
          />
          </div>

          {/* Info Panel (Collapsible) - Overlays map from right */}
          <InfoPanel
            changeset={changeset}
            routeNumber={routeNumber}
            selectedFeatureId={selectedFeatureId}
            selectedFeatureProperties={selectedFeatureProperties}
            localEventsCount={localEvents.length}
            onChangesetUpdate={handleChangesetUpdate}
            onSaveChanges={handleSaveChanges}
            onFeatureUpdate={handleEventAdded}
            loading={loading}
          />
        </div>
      </div>
    </>
  );
}

export default App;
