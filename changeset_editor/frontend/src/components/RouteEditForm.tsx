/**
 * Form component for editing route-level metadata (applies to all segments in route)
 */
import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';
import type { Changeset, SegmentUpdateAttrsEvent, RouteSegmentsResponse } from '../types';
import './RouteEditForm.css';

interface RouteAttributes {
  rutenummer?: string;
  rutenavn?: string;
  vedlikeholdsansvarlig?: string;
  rutetype?: string;
  gradering?: string;
  [key: string]: unknown;
}

interface RouteEditFormProps {
  changeset: Changeset;
  routeNumber: string;
  currentAttributes?: RouteAttributes;
  onSave: () => void;
  onCancel: () => void;
}

/**
 * Generate JSON Patch operations from old and new attribute values
 */
function generatePatch(
  oldAttrs: RouteAttributes,
  newAttrs: RouteAttributes
): Array<{ op: 'replace' | 'add' | 'remove'; path: string; value?: unknown }> {
  const patch: Array<{ op: 'replace' | 'add' | 'remove'; path: string; value?: unknown }> = [];
  
  // Fields to check (common route attributes)
  const fieldsToCheck = ['rutenummer', 'rutenavn', 'vedlikeholdsansvarlig', 'rutetype', 'gradering'];
  
  // Also check for any other keys in newAttrs that aren't in the standard list
  const allKeys = new Set([...Object.keys(oldAttrs), ...Object.keys(newAttrs)]);
  
  for (const key of allKeys) {
    // Skip internal fields
    if (key === 'op' || key === 'id' || key === 'objid' || key === 'segment_objid') {
      continue;
    }
    
    const oldValue = oldAttrs[key];
    const newValue = newAttrs[key];

    if (oldValue === undefined && newValue !== undefined && newValue !== '') {
      // Add new attribute
      patch.push({ op: 'add', path: `/${key}`, value: newValue });
    } else if (oldValue !== undefined && (newValue === undefined || newValue === '')) {
      // Remove attribute (only for standard fields)
      if (fieldsToCheck.includes(key)) {
        patch.push({ op: 'remove', path: `/${key}` });
      }
    } else if (oldValue !== newValue) {
      // Replace attribute
      patch.push({ op: 'replace', path: `/${key}`, value: newValue });
    }
  }

  return patch;
}

export function RouteEditForm({
  changeset,
  routeNumber,
  currentAttributes = {},
  onSave,
  onCancel,
}: RouteEditFormProps) {
  const [attributes, setAttributes] = useState<RouteAttributes>(currentAttributes);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingSegments, setIsLoadingSegments] = useState(false);
  const [segmentCount, setSegmentCount] = useState<number | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Load segments count when component mounts
  useEffect(() => {
    const loadSegments = async () => {
      setIsLoadingSegments(true);
      try {
        const data: RouteSegmentsResponse = await fetch(
          `/api/v1/routes/${routeNumber}/segments?include_geometry=false`
        ).then(res => {
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
          }
          return res.json();
        });
        setSegmentCount(data.segments?.length || 0);
      } catch (error: unknown) {
        const appError = handleApiError(error, 'Load Route Segments');
        notificationManager.warning(`Kunne ikke laste segmenter: ${appError.message}`);
      } finally {
        setIsLoadingSegments(false);
      }
    };

    loadSegments();
  }, [routeNumber]);

  // Update form when currentAttributes change
  useEffect(() => {
    setAttributes(currentAttributes);
    setErrors({});
  }, [currentAttributes, routeNumber]);

  const handleChange = (field: string, value: string) => {
    setAttributes((prev) => ({
      ...prev,
      [field]: value || undefined, // Convert empty string to undefined
    }));
    // Clear error for this field
    if (errors[field]) {
      setErrors((prev) => {
        const newErrors = { ...prev };
        delete newErrors[field];
        return newErrors;
      });
    }
  };

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};

    // Validate rutenummer format (if provided)
    const rutenummer = attributes.rutenummer?.trim();
    if (rutenummer && rutenummer.length > 0 && !/^[A-Z]{2,4}\d+$/i.test(rutenummer)) {
      newErrors.rutenummer = 'Rutenummer må være på formatet BRE017 (2-4 bokstaver + tall)';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!validate()) {
      notificationManager.warning('Vennligst rett valideringsfeil før lagring');
      return;
    }

    // Generate JSON Patch
    const patch = generatePatch(currentAttributes, attributes);

    if (patch.length === 0) {
      notificationManager.info('Ingen endringer å lagre');
      onCancel();
      return;
    }

    // Confirm bulk update
    if (segmentCount === null || segmentCount === 0) {
      notificationManager.warning('Ingen segmenter funnet for denne ruten');
      return;
    }

    if (!confirm(
      `Er du sikker på at du vil oppdatere metadata for alle ${segmentCount} segmenter i ruten "${routeNumber}"?`
    )) {
      return;
    }

    setIsSaving(true);
    try {
      // Load all segments for the route
      const data: RouteSegmentsResponse = await fetch(
        `/api/v1/routes/${routeNumber}/segments?include_geometry=false`
      ).then(res => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        return res.json();
      });

      if (!data.segments || data.segments.length === 0) {
        notificationManager.warning('Ingen segmenter funnet for denne ruten');
        setIsSaving(false);
        return;
      }

      // Create update events for all segments
      const events: SegmentUpdateAttrsEvent[] = data.segments.map((segment) => ({
        type: 'segment.update_attrs',
        target: { kind: 'segment', id: String(segment.segment_objid || segment.objid) },
        patch,
      }));

      // Send all events
      for (const event of events) {
        await api.addEvent(changeset.id, event);
      }

      notificationManager.success(
        `Metadata oppdatert for ${events.length} segmenter i ruten "${routeNumber}"`
      );
      onSave();
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Update Route Attributes');
      notificationManager.error(`Kunne ikke oppdatere metadata: ${appError.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <form className="route-edit-form" onSubmit={handleSubmit}>
      {isLoadingSegments ? (
        <div style={{ padding: '1rem', textAlign: 'center', color: '#666' }}>
          Laster segmenter...
        </div>
      ) : segmentCount !== null ? (
        <div style={{ 
          padding: '0.75rem', 
          marginBottom: '1rem', 
          background: '#e7f3ff', 
          borderRadius: '4px',
          fontSize: '0.85rem',
          color: '#0066cc'
        }}>
          <strong>Bulk-oppdatering:</strong> Endringer vil bli applisert til alle {segmentCount} segmenter i ruten.
        </div>
      ) : null}

      <div className="form-group">
        <label htmlFor="rutenummer">
          Rutenummer <span className="field-optional">(valgfritt)</span>
        </label>
        <input
          id="rutenummer"
          type="text"
          value={attributes.rutenummer || ''}
          onChange={(e) => handleChange('rutenummer', e.target.value)}
          placeholder="f.eks. BRE017"
          className={errors.rutenummer ? 'input-error' : ''}
        />
        {errors.rutenummer && (
          <span className="error-message">{errors.rutenummer}</span>
        )}
      </div>

      <div className="form-group">
        <label htmlFor="rutenavn">
          Rutenavn <span className="field-optional">(valgfritt)</span>
        </label>
        <input
          id="rutenavn"
          type="text"
          value={attributes.rutenavn || ''}
          onChange={(e) => handleChange('rutenavn', e.target.value)}
          placeholder="f.eks. Breivasshytta - Gjendesheim"
        />
      </div>

      <div className="form-group">
        <label htmlFor="vedlikeholdsansvarlig">
          Vedlikeholdsansvarlig <span className="field-optional">(valgfritt)</span>
        </label>
        <input
          id="vedlikeholdsansvarlig"
          type="text"
          value={attributes.vedlikeholdsansvarlig || ''}
          onChange={(e) => handleChange('vedlikeholdsansvarlig', e.target.value)}
          placeholder="f.eks. DNT Oslo og Omegn"
        />
      </div>

      <div className="form-group">
        <label htmlFor="rutetype">
          Rutetype <span className="field-optional">(valgfritt)</span>
        </label>
        <select
          id="rutetype"
          value={attributes.rutetype || ''}
          onChange={(e) => handleChange('rutetype', e.target.value)}
        >
          <option value="">-- Velg rutetype --</option>
          <option value="fotrute">Fotrute</option>
          <option value="sykkelrute">Sykkelrute</option>
          <option value="skiløype">Skiløype</option>
          <option value="kombinasjonsrute">Kombinasjonsrute</option>
        </select>
      </div>

      <div className="form-group">
        <label htmlFor="gradering">
          Gradering <span className="field-optional">(valgfritt)</span>
        </label>
        <select
          id="gradering"
          value={attributes.gradering || ''}
          onChange={(e) => handleChange('gradering', e.target.value)}
        >
          <option value="">-- Velg gradering --</option>
          <option value="grønn">Grønn</option>
          <option value="blå">Blå</option>
          <option value="rød">Rød</option>
          <option value="svart">Svart</option>
        </select>
      </div>

      <div className="form-actions">
        <button type="button" onClick={onCancel} className="btn btn-secondary" disabled={isSaving}>
          Avbryt
        </button>
        <button type="submit" className="btn btn-primary" disabled={isSaving || isLoadingSegments}>
          {isSaving ? 'Lagrer...' : `Lagre for alle segmenter`}
        </button>
      </div>
    </form>
  );
}
