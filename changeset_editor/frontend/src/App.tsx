/** Main App component */
import { useState, useEffect } from 'react';
import { MapView } from './components/MapView';
import { Header } from './components/Header';
import { InfoPanel } from './components/InfoPanel';
import { NotificationContainer } from './components/NotificationContainer';
import { api } from './api/client';
import { handleApiError } from './utils/errorHandler';
import { notificationManager } from './utils/notifications';
import { saveChangesetToFile, loadChangesetFromFile } from './utils/fileStorage';
import type { Changeset, LocalEvent, RouteResponse } from './types';
import './App.css';

function App() {
  const [changeset, setChangeset] = useState<Changeset | null>(null);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | undefined>();
  const [selectedFeatureProperties, setSelectedFeatureProperties] = useState<Record<string, unknown> | null>(null);
  const [selectedFeatureIds, setSelectedFeatureIds] = useState<Set<string>>(new Set()); // Multi-select support
  const [selectedFeaturesMap, setSelectedFeaturesMap] = useState<Map<string, Record<string, unknown>>>(new Map()); // Map of feature ID to properties
  const [loading, setLoading] = useState(true);
  const [shouldOpenEditForm, setShouldOpenEditForm] = useState(false);

  const [routeNumber, setRouteNumber] = useState<string | null>(null);
  const [selectedRouteNumber, setSelectedRouteNumber] = useState<string | null>(null);
  const [routeGeometry, setRouteGeometry] = useState<GeoJSON.Geometry | null>(null);
  const [selectedArea, setSelectedArea] = useState<string | null>(null); // Area prefix (e.g., 'bre', 'jot')

  // Local changes (before changeset is created)
  const [localEvents, setLocalEvents] = useState<LocalEvent[]>([]);

  // Signs state
  const [signsPrefix, setSignsPrefix] = useState<string>('');
  const [selectedSignDestinations, setSelectedSignDestinations] = useState<Set<string>>(new Set());

  // Mode management
  type AppMode = 'inspection' | 'edit' | 'anchor-naming' | 'signs' | 'property-ownership';
  const [activeMode, setActiveMode] = useState<AppMode>('inspection');
  
  // Property ownership state
  const [selectedGeometryForOwnership, setSelectedGeometryForOwnership] = useState<GeoJSON.Geometry | null>(null);
  const [ownershipData, setOwnershipData] = useState<any>(null);

  const handleSignDestinationSelect = (destKey: string, selected: boolean) => {
    setSelectedSignDestinations(prev => {
      const newSet = new Set(prev);
      if (selected) {
        newSet.add(destKey);
      } else {
        newSet.delete(destKey);
      }
      return newSet;
    });
  };

  const handleSignsPrefixChange = (prefix: string) => {
    setSignsPrefix(prefix);
  };

  // Get changeset ID or route number from URL
  useEffect(() => {
    const loadInitialData = async () => {
      const urlParams = new URLSearchParams(window.location.search);
      const changesetId = urlParams.get('changeset');
      const route = urlParams.get('route');
      const tasks: Promise<unknown>[] = [];

      if (route && route.trim() !== '') {
        setRouteNumber(route);
        setSelectedRouteNumber(route);
        tasks.push(
          api.getRoute(route, true)
            .then((data: RouteResponse) => setRouteGeometry(data.route_geometry || null))
            .catch((error) => {
              const appError = handleApiError(error, 'Route Geometry Load');
              notificationManager.error(`Kunne ikke laste rutegeometri: ${appError.message}`);
            })
        );
      }

      if (changesetId) {
        tasks.push(
          api.getChangeset(changesetId)
            .then(setChangeset)
            .catch((error) => {
              const appError = handleApiError(error, 'Changeset Load');
              notificationManager.error(`Kunne ikke laste changeset: ${appError.message}`);
            })
        );
      }

      await Promise.allSettled(tasks);
      setLoading(false);
    };

    loadInitialData();
  }, []);

  const handleSelectRoute = async (rutenummer: string | null) => {
    // Handle deselection
    if (!rutenummer || rutenummer.trim() === '') {
      setSelectedRouteNumber(null);
      setRouteNumber(null);
      setRouteGeometry(null);
      // Update URL to remove route parameter
      const urlParams = new URLSearchParams(window.location.search);
      urlParams.delete('route');
      const newUrl = urlParams.toString() ? `?${urlParams.toString()}` : window.location.pathname;
      window.history.replaceState({}, '', newUrl);
      return;
    }

    setSelectedRouteNumber(rutenummer);
    setLoading(true);
    try {
      // Load route geometry and display on map
      const routeData = await api.getRoute(rutenummer, true);
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

  // Save locally: Export to file (no changeset creation)
  const handleSaveLocally = () => {
    if (!routeNumber || localEvents.length === 0) {
      notificationManager.warning('Ingen endringer å lagre');
      return;
    }

    try {
      saveChangesetToFile(changeset, localEvents, routeNumber);
      notificationManager.success(`Endringer eksportert til fil (${localEvents.length} events)`);
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Save Locally');
      notificationManager.error(`Kunne ikke eksportere til fil: ${appError.message}`);
    }
  };

  // Load from file
  const handleLoadFromFile = async (file: File) => {
    setLoading(true);
    try {
      const data = await loadChangesetFromFile(file);

      // Restore changeset if present
      if (data.changeset) {
        setChangeset(data.changeset);
        // Update URL
        if (data.routeNumber) {
          window.history.replaceState({}, '', `?route=${data.routeNumber}&changeset=${data.changeset.id}`);
        }
      } else {
        // Restore local events
        setLocalEvents(data.events as LocalEvent[]);
        if (data.routeNumber) {
          setRouteNumber(data.routeNumber);
          window.history.replaceState({}, '', `?route=${data.routeNumber}`);
        }
      }

      notificationManager.success(`Changeset lastet fra fil (${data.events.length} events)`);
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Load From File');
      notificationManager.error(`Kunne ikke laste fil: ${appError.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Publish: Create changeset and send to backend
  const handlePublish = async () => {
    if (!routeNumber) {
      notificationManager.warning('Velg en rute først');
      return;
    }

    // If we already have a changeset, just publish it
    if (changeset) {
      setLoading(true);
      try {
        const result = await api.publish(changeset.id);
        notificationManager.success(
          `Changeset publisert! PR: ${result.pr_url || 'N/A'}`,
          0 // Don't auto-dismiss
        );
        // Reload changeset to get updated status
        const updatedChangeset = await api.getChangeset(changeset.id);
        setChangeset(updatedChangeset);
      } catch (error: unknown) {
        const appError = handleApiError(error, 'Publish');
        notificationManager.error(`Kunne ikke publisere: ${appError.message}`);
      } finally {
        setLoading(false);
      }
      return;
    }

    // If no changeset but we have local events, create changeset first
    if (localEvents.length === 0) {
      notificationManager.warning('Ingen endringer å publisere');
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

      try {
        // Send all local events to changeset
        for (const event of localEvents) {
          await api.addEvent(newChangeset.id, event);
        }
      } catch (error: unknown) {
        const appError = handleApiError(error, 'Add Events');
        notificationManager.error(
          `Kunne ikke legge til alle endringer i changeset: ${appError.message}`
        );
        notificationManager.warning(
          `Changeset ${newChangeset.id} er opprettet, men kan være ufullstendig.`
        );
        return;
      }

      // Events added successfully; move into changeset state
      setChangeset(newChangeset);
      setLocalEvents([]); // Clear local events after successful event transfer

      // Update URL with changeset
      window.history.replaceState({}, '', `?route=${routeNumber}&changeset=${newChangeset.id}`);

      // Publish the changeset
      try {
        const result = await api.publish(newChangeset.id);
        notificationManager.success(
          `Changeset opprettet og publisert! PR: ${result.pr_url || 'N/A'}`,
          0 // Don't auto-dismiss
        );
      } catch (error: unknown) {
        const appError = handleApiError(error, 'Publish');
        notificationManager.error(`Kunne ikke publisere: ${appError.message}`);
        notificationManager.info(
          `Changeset ${newChangeset.id} er opprettet og klar for nytt publiseringsforsøk.`
        );
      }
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Publish');
      notificationManager.error(`Kunne ikke publisere: ${appError.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleEventAdded = (_event?: unknown) => {
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
          changeset={changeset}
          localEventsCount={localEvents.length}
          onSaveChanges={handleSaveLocally}
          onLoadFromFile={handleLoadFromFile}
          onPublish={handlePublish}
          selectedArea={selectedArea}
          onAreaChange={setSelectedArea}
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
            selectedFeatureIds={selectedFeatureIds}
            signsPrefix={signsPrefix}
            onSignDestinationSelect={handleSignDestinationSelect}
            selectedSignDestinations={selectedSignDestinations}
            activeMode={activeMode}
            onModeChange={setActiveMode}
            selectedGeometryForOwnership={selectedGeometryForOwnership}
            onGeometrySelectForOwnership={setSelectedGeometryForOwnership}
            ownershipData={ownershipData}
            onOwnershipDataChange={setOwnershipData}
            selectedArea={selectedArea}
            onFeatureSelect={(id, properties, isMultiSelect) => {
              if (isMultiSelect) {
                // Multi-select mode: toggle selection
                setSelectedFeatureIds(prev => {
                  const newSet = new Set(prev);
                  if (newSet.has(id)) {
                    newSet.delete(id);
                    setSelectedFeaturesMap(prevMap => {
                      const newMap = new Map(prevMap);
                      newMap.delete(id);
                      return newMap;
                    });
                  } else {
                    newSet.add(id);
                    setSelectedFeaturesMap(prevMap => {
                      const newMap = new Map(prevMap);
                      if (properties) {
                        newMap.set(id, properties);
                      }
                      return newMap;
                    });
                  }
                  return newSet;
                });
                // Also set as primary selection
                setSelectedFeatureId(id);
                setSelectedFeatureProperties(properties || null);
              } else {
                // Single select mode: clear multi-select and set single
                setSelectedFeatureIds(new Set([id]));
                setSelectedFeaturesMap(new Map(properties ? [[id, properties]] : []));
                setSelectedFeatureId(id);
                setSelectedFeatureProperties(properties || null);
              }
            }}
            onOpenEditForm={() => {
              // Trigger edit form opening in InfoPanel
              setShouldOpenEditForm(true);
            }}
            localEventsCount={localEvents.length}
          />
          </div>

          {/* Info Panel (Collapsible) - Overlays map from right */}
          <InfoPanel
            changeset={changeset}
            routeNumber={routeNumber}
            selectedFeatureId={selectedFeatureId}
            selectedFeatureIds={selectedFeatureIds}
            selectedFeatureProperties={selectedFeatureProperties}
            selectedFeaturesMap={selectedFeaturesMap}
            localEvents={localEvents}
            localEventsCount={localEvents.length}
            onChangesetUpdate={handleChangesetUpdate}
            onSaveChanges={handleSaveLocally}
            onLoadFromFile={handleLoadFromFile}
            onPublish={handlePublish}
            onFeatureUpdate={changeset ? handleEventAdded : () => {
              // This is called from InfoPanel after events are added
              // The actual event is already added via onEventAdded in MapView
            }}
            loading={loading}
            shouldOpenEditForm={shouldOpenEditForm}
            onEditFormOpened={() => setShouldOpenEditForm(false)}
            selectedSignDestinations={selectedSignDestinations}
            onSignDestinationSelect={handleSignDestinationSelect}
            onSignsPrefixChange={handleSignsPrefixChange}
            activeMode={activeMode}
            ownershipData={ownershipData}
            selectedGeometryForOwnership={selectedGeometryForOwnership}
            onOwnershipDataChange={setOwnershipData}
          />
        </div>
      </div>
    </>
  );
}

export default App;
