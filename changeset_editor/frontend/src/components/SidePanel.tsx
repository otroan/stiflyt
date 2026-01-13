/** Side panel for changeset metadata and feature editing */
import { useState, useEffect } from 'react';
import type { Changeset, ChangeEvent, ValidationIssue, EventPayload, SegmentAddEvent, SegmentUpdateGeomEvent } from '../types';
import { isSegmentAddEvent, isSegmentUpdateGeomEvent } from '../types';
import { api } from '../api/client';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';

interface SidePanelProps {
  changeset: Changeset;
  selectedFeatureId?: string;
  onChangesetUpdate: () => void;
}

export function SidePanel({
  changeset,
  selectedFeatureId,
  onChangesetUpdate,
}: SidePanelProps) {
  const [events, setEvents] = useState<ChangeEvent[]>([]);
  const [validation, setValidation] = useState<{ errors: ValidationIssue[]; warnings: ValidationIssue[] } | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);

  useEffect(() => {
    api.getEvents(changeset.id)
      .then((data) => setEvents(data.events))
      .catch((error) => {
        const appError = handleApiError(error, 'Load Events');
        notificationManager.error(`Kunne ikke laste events: ${appError.message}`);
      });
  }, [changeset.id]);

  const handleValidate = async () => {
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
    if (!confirm('Send changeset to review? This will create a GitHub PR.')) {
      return;
    }

    setIsPublishing(true);
    try {
      const result = await api.publish(changeset.id);
      notificationManager.success(
        `Changeset publisert! PR: ${result.pr_url || 'N/A'}`,
        0 // Don't auto-dismiss success for publish
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

  const selectedEvent = selectedFeatureId
    ? events.find((e) => {
        const event = e.event;
        if (isSegmentUpdateGeomEvent(event) || isSegmentAddEvent(event)) {
          if (isSegmentUpdateGeomEvent(event)) {
            return event.target.id === selectedFeatureId;
          }
          if (isSegmentAddEvent(event)) {
            return event.temp_id.includes(selectedFeatureId);
          }
        }
        return false;
      })
    : null;

  return (
    <div style={{
      width: '400px',
      height: '100%',
      background: 'white',
      borderLeft: '1px solid #ddd',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'auto',
    }}>
      {/* Changeset metadata */}
      <div style={{ padding: '16px', borderBottom: '1px solid #ddd' }}>
        <h2 style={{ margin: '0 0 8px 0' }}>{changeset.title}</h2>
        <p style={{ margin: '0 0 8px 0', color: '#666', fontSize: '0.9em' }}>
          {changeset.description || 'No description'}
        </p>
        <div style={{ fontSize: '0.85em', color: '#999' }}>
          <div>Status: <strong>{changeset.status}</strong></div>
          <div>Events: {events.length}</div>
          {changeset.pr_url && (
            <div>
              <a href={changeset.pr_url} target="_blank" rel="noopener noreferrer">
                View PR
              </a>
            </div>
          )}
        </div>
      </div>

      {/* Actions */}
      <div style={{ padding: '16px', borderBottom: '1px solid #ddd' }}>
        <button
          onClick={handleValidate}
          disabled={isValidating || changeset.status !== 'draft'}
          style={{
            width: '100%',
            padding: '8px',
            marginBottom: '8px',
            background: '#3498db',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
          }}
        >
          {isValidating ? 'Validating...' : 'Validate'}
        </button>
        <button
          onClick={handlePublish}
          disabled={isPublishing || changeset.status !== 'draft'}
          style={{
            width: '100%',
            padding: '8px',
            background: changeset.status === 'draft' ? '#2ecc71' : '#95a5a6',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
          }}
        >
          {isPublishing ? 'Publishing...' : 'Send to Review'}
        </button>
      </div>

      {/* Validation results */}
      {validation && (
        <div style={{ padding: '16px', borderBottom: '1px solid #ddd' }}>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '1em' }}>Validation</h3>
          {validation.errors.length > 0 && (
            <div style={{ marginBottom: '8px' }}>
              <strong style={{ color: '#e74c3c' }}>Errors ({validation.errors.length}):</strong>
              <ul style={{ margin: '4px 0', paddingLeft: '20px', fontSize: '0.85em' }}>
                {validation.errors.map((err, i) => (
                  <li key={i} style={{ color: '#e74c3c' }}>
                    {err.message} ({err.code})
                  </li>
                ))}
              </ul>
            </div>
          )}
          {validation.warnings.length > 0 && (
            <div>
              <strong style={{ color: '#f39c12' }}>Warnings ({validation.warnings.length}):</strong>
              <ul style={{ margin: '4px 0', paddingLeft: '20px', fontSize: '0.85em' }}>
                {validation.warnings.map((warn, i) => (
                  <li key={i} style={{ color: '#f39c12' }}>
                    {warn.message} ({warn.code})
                  </li>
                ))}
              </ul>
            </div>
          )}
          {validation.errors.length === 0 && validation.warnings.length === 0 && (
            <div style={{ color: '#2ecc71' }}>✓ No issues found</div>
          )}
        </div>
      )}

      {/* Selected feature */}
      {selectedFeatureId && selectedEvent && (
        <div style={{ padding: '16px', borderBottom: '1px solid #ddd' }}>
          <h3 style={{ margin: '0 0 8px 0', fontSize: '1em' }}>Selected Feature</h3>
          <div style={{ fontSize: '0.85em' }}>
            <div>ID: {selectedFeatureId}</div>
            <div>Type: {selectedEvent.event.type}</div>
            {/* Feature editing form would go here */}
          </div>
        </div>
      )}

      {/* Events list */}
      <div style={{ padding: '16px', flex: 1, overflow: 'auto' }}>
        <h3 style={{ margin: '0 0 8px 0', fontSize: '1em' }}>Events ({events.length})</h3>
        <div style={{ fontSize: '0.85em' }}>
          {events.map((event, i) => (
            <div
              key={event.event_id}
              style={{
                padding: '8px',
                marginBottom: '4px',
                background: '#f8f9fa',
                borderRadius: '4px',
              }}
            >
              <div style={{ fontWeight: 'bold' }}>
                {event.event.type}
              </div>
              <div style={{ color: '#666', fontSize: '0.9em' }}>
                {new Date(event.ts).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
