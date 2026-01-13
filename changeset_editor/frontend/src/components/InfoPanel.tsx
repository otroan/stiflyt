/**
 * Collapsible info panel component (replaces SidePanel)
 * Displays route info, changeset info, validation results, and events
 */
import { useState, useEffect } from 'react';
import type { Changeset, ChangeEvent, ValidationIssue } from '../types';
import { isSegmentAddEvent, isSegmentUpdateGeomEvent } from '../types';
import { api } from '../api/client';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';
import { SegmentEditForm } from './SegmentEditForm';
import { RouteEditForm } from './RouteEditForm';
import './InfoPanel.css';

interface InfoPanelProps {
  changeset: Changeset | null;
  routeNumber: string | null;
  selectedFeatureId?: string;
  selectedFeatureProperties?: Record<string, unknown> | null;
  localEventsCount?: number;
  onChangesetUpdate: () => void;
  onSaveChanges?: () => void;
  onFeatureUpdate?: () => void;
  loading?: boolean;
  onEditFormOpen?: (open: boolean) => void; // Callback to notify when edit form should open
}

export function InfoPanel({
  changeset,
  routeNumber,
  selectedFeatureId,
  selectedFeatureProperties,
  localEventsCount = 0,
  onChangesetUpdate,
  onSaveChanges,
  onFeatureUpdate,
  loading = false,
  onEditFormOpen,
}: InfoPanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [events, setEvents] = useState<ChangeEvent[]>([]);
  const [validation, setValidation] = useState<{ errors: ValidationIssue[]; warnings: ValidationIssue[] } | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [showEditForm, setShowEditForm] = useState(false);
  const [showRouteEditForm, setShowRouteEditForm] = useState(false);
  const [routeMetadata, setRouteMetadata] = useState<Record<string, unknown> | null>(null);

  // Auto-open panel when changeset is loaded or route is selected
  useEffect(() => {
    if (changeset || routeNumber) {
      setIsOpen(true);
    }
  }, [changeset?.id, routeNumber]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (changeset) {
      api.getEvents(changeset.id)
        .then((data) => setEvents(data.events))
        .catch((error) => {
          const appError = handleApiError(error, 'Load Events');
          notificationManager.error(`Kunne ikke laste events: ${appError.message}`);
        });
    } else {
      setEvents([]);
    }
  }, [changeset?.id]);

  // Load route metadata when route is selected
  useEffect(() => {
    if (routeNumber && changeset) {
      fetch(`/api/v1/routes/${routeNumber}`)
        .then(res => {
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
          }
          return res.json();
        })
        .then((data) => {
          setRouteMetadata({
            rutenummer: data.rutenummer,
            rutenavn: data.rutenavn,
            vedlikeholdsansvarlig: data.vedlikeholdsansvarlig,
            rutetype: data.rutetype,
            gradering: data.gradering,
          });
        })
        .catch((error) => {
          // Silently fail - route metadata is optional
          console.warn('Could not load route metadata:', error);
        });
    } else {
      setRouteMetadata(null);
    }
  }, [routeNumber, changeset?.id]);

  const handleValidate = async () => {
    if (!changeset) return;
    
    setIsValidating(true);
    try {
      const result = await api.validate(changeset.id);
      setValidation(result);
      if (result.errors.length === 0 && result.warnings.length === 0) {
        notificationManager.success('Validering fullført: Ingen feil funnet');
      } else {
        notificationManager.warning(
          `Validering fullført: ${result.errors.length} feil, ${result.warnings.length} advarsler`
        );
      }
    } catch (error) {
      const appError = handleApiError(error, 'Validation');
      notificationManager.error(`Validering feilet: ${appError.message}`);
    } finally {
      setIsValidating(false);
    }
  };

  const handlePublish = async () => {
    if (!changeset) return;
    
    if (!confirm('Send changeset to review? This will create a GitHub PR.')) {
      return;
    }

    setIsPublishing(true);
    try {
      const result = await api.publish(changeset.id);
      notificationManager.success(
        `Changeset publisert! PR: ${result.pr_url || 'N/A'}`,
        0
      );
      onChangesetUpdate();
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Publish');
      
      // Try to extract validation errors from response
      if (error && typeof error === 'object' && 'response' in error) {
        try {
          const errorWithResponse = error as { response?: { json: () => Promise<unknown> } };
          const errorData = errorWithResponse.response 
            ? await errorWithResponse.response.json().catch(() => null)
            : null;
          
          if (errorData && typeof errorData === 'object' && errorData !== null) {
            const validationData = errorData as { errors?: ValidationIssue[]; warnings?: ValidationIssue[] };
            if (validationData.errors) {
              setValidation({ 
                errors: validationData.errors, 
                warnings: validationData.warnings || [] 
              });
              notificationManager.error(
                `Publisering feilet: ${validationData.errors.length} feil funnet. Se valideringspanel.`,
                0
              );
              return;
            }
          }
        } catch {
          // Ignore JSON parse errors
        }
      }
      
      notificationManager.error(`Publisering feilet: ${appError.message}`, 0);
    } finally {
      setIsPublishing(false);
    }
  };

  const selectedEvent = selectedFeatureId && changeset
    ? events.find((e) => {
        const event = e.event;
        if (isSegmentUpdateGeomEvent(event) || isSegmentAddEvent(event) || event.type === 'segment.update_attrs') {
          if (isSegmentUpdateGeomEvent(event) || event.type === 'segment.update_attrs') {
            return (event as { target?: { id?: string } }).target?.id === selectedFeatureId;
          }
          if (isSegmentAddEvent(event)) {
            return event.temp_id.includes(selectedFeatureId);
          }
        }
        return false;
      })
    : null;
  
  // Extract segment attributes from properties
  // Properties from effective/diff layer contain the current attributes
  const segmentAttributes = selectedFeatureProperties 
    ? {
        rutenummer: selectedFeatureProperties.rutenummer || selectedFeatureProperties.route_ref,
        rutenavn: selectedFeatureProperties.rutenavn || selectedFeatureProperties.name,
        vedlikeholdsansvarlig: selectedFeatureProperties.vedlikeholdsansvarlig,
        rutetype: selectedFeatureProperties.rutetype,
        gradering: selectedFeatureProperties.gradering,
        ...selectedFeatureProperties, // Include all other properties
      } as Record<string, unknown>
    : null;

  return (
    <>
      {/* Toggle button - shown when panel is closed */}
      {!isOpen && (
        <button
          className="info-panel-toggle"
          onClick={() => setIsOpen(true)}
          aria-label="Åpne informasjonspanel"
          title="Åpne informasjonspanel"
        >
          ☰
        </button>
      )}

      {/* Info Panel */}
      <div className={`info-panel ${isOpen ? 'info-panel-open' : ''}`}>
        <div className="info-panel-header">
          <h2 className="info-panel-title">
            {changeset 
              ? `Redigering: ${routeNumber || 'Rute'}` 
              : routeNumber 
                ? `Rute: ${routeNumber}` 
                : 'Informasjon'}
          </h2>
          <button
            className="info-panel-close"
            onClick={() => setIsOpen(false)}
            aria-label="Lukk panel"
          >
            ×
          </button>
        </div>

        <div className="info-panel-content">
          {!changeset && !routeNumber ? (
            <div className="info-panel-empty">
              <p>Velg en rute for å se informasjon</p>
            </div>
          ) : changeset ? (
            <>
              {/* Changeset metadata */}
              <div className="info-panel-section">
                <h3>Changeset</h3>
                <div className="info-panel-item">
                  <span className="info-label">Tittel:</span>
                  <span>{changeset.title}</span>
                </div>
                {changeset.description && (
                  <div className="info-panel-item">
                    <span className="info-label">Beskrivelse:</span>
                    <span>{changeset.description}</span>
                  </div>
                )}
                <div className="info-panel-item">
                  <span className="info-label">Status:</span>
                  <span className={`status-badge status-${changeset.status}`}>
                    {changeset.status}
                  </span>
                </div>
                <div className="info-panel-item">
                  <span className="info-label">Events:</span>
                  <span>{events.length}</span>
                </div>
                {changeset.pr_url && (
                  <div className="info-panel-item">
                    <span className="info-label">PR:</span>
                    <a href={changeset.pr_url} target="_blank" rel="noopener noreferrer">
                      Vis PR
                    </a>
                  </div>
                )}
              </div>

              {/* Actions */}
              <div className="info-panel-section">
                <h3>Handlinger</h3>
                <div className="info-panel-actions">
                  <button
                    onClick={handleValidate}
                    disabled={isValidating || changeset.status !== 'draft'}
                    className="btn btn-primary"
                  >
                    {isValidating ? 'Validerer...' : 'Valider'}
                  </button>
                  <button
                    onClick={handlePublish}
                    disabled={isPublishing || changeset.status !== 'draft'}
                    className="btn btn-success"
                  >
                    {isPublishing ? 'Publiserer...' : 'Send til Review'}
                  </button>
                </div>
              </div>

              {/* Validation results */}
              {validation && (
                <div className="info-panel-section">
                  <h3>Validering</h3>
                  {validation.errors.length > 0 && (
                    <div className="validation-errors">
                      <strong style={{ color: '#e74c3c' }}>
                        Feil ({validation.errors.length}):
                      </strong>
                      <ul>
                        {validation.errors.map((err, i) => (
                          <li key={i} style={{ color: '#e74c3c' }}>
                            {err.message} ({err.code})
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {validation.warnings.length > 0 && (
                    <div className="validation-warnings">
                      <strong style={{ color: '#f39c12' }}>
                        Advarsler ({validation.warnings.length}):
                      </strong>
                      <ul>
                        {validation.warnings.map((warn, i) => (
                          <li key={i} style={{ color: '#f39c12' }}>
                            {warn.message} ({warn.code})
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {validation.errors.length === 0 && validation.warnings.length === 0 && (
                    <div style={{ color: '#2ecc71' }}>✓ Ingen problemer funnet</div>
                  )}
                </div>
              )}

              {/* Route editing (when route is selected but no segment) */}
              {!selectedFeatureId && routeNumber && changeset && (
                <div className="info-panel-section">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <h3 style={{ margin: 0 }}>Rute: {routeNumber}</h3>
                    {!showRouteEditForm && (
                      <button
                        onClick={() => setShowRouteEditForm(true)}
                        className="btn btn-primary"
                        style={{ fontSize: '0.85rem', padding: '0.5rem 0.75rem' }}
                      >
                        Rediger rute-metadata
                      </button>
                    )}
                  </div>
                  
                  {showRouteEditForm && changeset ? (
                    <RouteEditForm
                      changeset={changeset}
                      routeNumber={routeNumber}
                      currentAttributes={(routeMetadata || {}) as Record<string, unknown>}
                      onSave={() => {
                        setShowRouteEditForm(false);
                        onChangesetUpdate();
                        // Reload route metadata
                        fetch(`/api/v1/routes/${routeNumber}`)
                          .then(res => res.json())
                          .then((data) => {
                            setRouteMetadata({
                              rutenummer: data.rutenummer,
                              rutenavn: data.rutenavn,
                              vedlikeholdsansvarlig: data.vedlikeholdsansvarlig,
                              rutetype: data.rutetype,
                              gradering: data.gradering,
                            });
                          })
                          .catch(() => {
                            // Ignore errors
                          });
                      }}
                      onCancel={() => setShowRouteEditForm(false)}
                    />
                  ) : (
                    <>
                      {routeMetadata ? (
                        <>
                          {routeMetadata.rutenavn && (
                            <div className="info-panel-item">
                              <span className="info-label">Rutenavn:</span>
                              <span>{String(routeMetadata.rutenavn)}</span>
                            </div>
                          )}
                          {routeMetadata.vedlikeholdsansvarlig && (
                            <div className="info-panel-item">
                              <span className="info-label">Vedlikeholdsansvarlig:</span>
                              <span>{String(routeMetadata.vedlikeholdsansvarlig)}</span>
                            </div>
                          )}
                          {routeMetadata.rutetype && (
                            <div className="info-panel-item">
                              <span className="info-label">Rutetype:</span>
                              <span>{String(routeMetadata.rutetype)}</span>
                            </div>
                          )}
                          {routeMetadata.gradering && (
                            <div className="info-panel-item">
                              <span className="info-label">Gradering:</span>
                              <span>{String(routeMetadata.gradering)}</span>
                            </div>
                          )}
                        </>
                      ) : (
                        <div className="info-panel-item" style={{ color: '#666', fontStyle: 'italic' }}>
                          Laster rute-metadata...
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* Selected feature */}
              {selectedFeatureId && selectedEvent && (
                <div className="info-panel-section">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <h3 style={{ margin: 0 }}>Valgt element</h3>
                    {!showEditForm && (
                      <button
                        onClick={() => setShowEditForm(true)}
                        className="btn btn-primary"
                        style={{ fontSize: '0.85rem', padding: '0.5rem 0.75rem' }}
                      >
                        Rediger metadata
                      </button>
                    )}
                  </div>
                  
                  {showEditForm && changeset ? (
                    <SegmentEditForm
                      changeset={changeset}
                      segmentId={selectedFeatureId}
                      currentAttributes={segmentAttributes || {}}
                      onSave={() => {
                        setShowEditForm(false);
                        if (onFeatureUpdate) {
                          onFeatureUpdate();
                        }
                        onChangesetUpdate();
                      }}
                      onCancel={() => setShowEditForm(false)}
                    />
                  ) : (
                    <>
                      <div className="info-panel-item">
                        <span className="info-label">ID:</span>
                        <span>{selectedFeatureId}</span>
                      </div>
                      <div className="info-panel-item">
                        <span className="info-label">Type:</span>
                        <span>{selectedEvent.event.type}</span>
                      </div>
                      {selectedFeatureProperties && (
                        <>
                          {selectedFeatureProperties.rutenummer && (
                            <div className="info-panel-item">
                              <span className="info-label">Rutenummer:</span>
                              <span>{String(selectedFeatureProperties.rutenummer)}</span>
                            </div>
                          )}
                          {selectedFeatureProperties.rutenavn && (
                            <div className="info-panel-item">
                              <span className="info-label">Rutenavn:</span>
                              <span>{String(selectedFeatureProperties.rutenavn)}</span>
                            </div>
                          )}
                          {selectedFeatureProperties.vedlikeholdsansvarlig && (
                            <div className="info-panel-item">
                              <span className="info-label">Vedlikeholdsansvarlig:</span>
                              <span>{String(selectedFeatureProperties.vedlikeholdsansvarlig)}</span>
                            </div>
                          )}
                        </>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* Events list */}
              <div className="info-panel-section">
                <h3>Events ({events.length})</h3>
                <div className="events-list">
                  {events.map((event) => (
                    <div key={event.event_id} className="event-item">
                      <div className="event-type">{event.event.type}</div>
                      <div className="event-time">
                        {new Date(event.ts).toLocaleString()}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          ) : routeNumber ? (
            <>
              {/* Route info (no changeset yet) */}
              <div className="info-panel-section">
                <h3>Rute: {routeNumber}</h3>
                <p style={{ color: '#666', marginBottom: '1rem' }}>
                  Ruten er valgt og vises på kartet. Gjør endringer på kartet.
                </p>

                {/* Show pending changes count and Save button */}
                {localEventsCount > 0 && onSaveChanges && (
                  <div className="pending-changes-banner">
                    <div style={{ marginBottom: '8px' }}>
                      <strong>Ulagrede endringer: {localEventsCount}</strong>
                    </div>
                    <button
                      onClick={onSaveChanges}
                      disabled={loading}
                      className="btn btn-success"
                      style={{ width: '100%' }}
                    >
                      {loading ? 'Lagrer...' : '💾 Lagre endringer'}
                    </button>
                  </div>
                )}

                <p style={{ marginTop: '12px', fontSize: '12px', color: '#666', fontStyle: 'italic' }}>
                  Bruk verktøyene på venstre side av kartet for å gjøre endringer.
                </p>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </>
  );
}
