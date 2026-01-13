/** Side panel for changeset metadata and feature editing */
import { useState, useEffect } from 'react';
import type { Changeset, ChangeEvent, ValidationIssue } from '../types';
import { api } from '../api/client';

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
      .catch(console.error);
  }, [changeset.id]);

  const handleValidate = async () => {
    setIsValidating(true);
    try {
      const result = await api.validate(changeset.id);
      setValidation(result);
    } catch (error) {
      console.error('Validation failed:', error);
      alert(`Validation failed: ${error}`);
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
      alert(`Changeset published! PR: ${result.pr_url || 'N/A'}`);
      onChangesetUpdate();
    } catch (error: any) {
      console.error('Publish failed:', error);
      if (error.message?.includes('errors')) {
        const errorData = await error.response?.json().catch(() => null);
        if (errorData?.errors) {
          setValidation({ errors: errorData.errors, warnings: errorData.warnings || [] });
          alert(`Publish failed: ${errorData.errors.length} errors found. See validation panel.`);
        } else {
          alert(`Publish failed: ${error}`);
        }
      } else {
        alert(`Publish failed: ${error}`);
      }
    } finally {
      setIsPublishing(false);
    }
  };

  const selectedEvent = selectedFeatureId
    ? events.find((e) => {
        const target = (e.event as any).target;
        return target?.id === selectedFeatureId || (e.event as any).temp_id?.includes(selectedFeatureId);
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
            <div>Type: {(selectedEvent.event as any).type}</div>
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
                {(event.event as any).type}
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
