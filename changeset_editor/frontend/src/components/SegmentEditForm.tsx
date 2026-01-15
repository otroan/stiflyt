/**
 * Form component for editing segment metadata/attributes
 */
import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';
import type { Changeset, SegmentUpdateAttrsEvent } from '../types';
import './SegmentEditForm.css';

interface SegmentAttributes {
  rutenummer?: string;
  rutenavn?: string;
  vedlikeholdsansvarlig?: string;
  rutetype?: string;
  gradering?: string;
  route_ref?: string; // Alternative field name
  name?: string; // Alternative field name
  [key: string]: unknown; // Allow other attributes
}

interface SegmentEditFormProps {
  changeset: Changeset | null;
  segmentId: string;
  currentAttributes?: SegmentAttributes;
  onSave: () => void;
  onCancel: () => void;
  onEventAdded?: (event: SegmentUpdateAttrsEvent) => void; // For localEvents when no changeset
}

/**
 * Generate JSON Patch operations from old and new attribute values
 */
/**
 * Generate JSON Patch operations from old and new attribute values
 * Handles normalization of field names (route_ref -> rutenummer, name -> rutenavn)
 */
function generatePatch(
  oldAttrs: SegmentAttributes,
  newAttrs: SegmentAttributes
): Array<{ op: 'replace' | 'add' | 'remove'; path: string; value?: unknown }> {
  const patch: Array<{ op: 'replace' | 'add' | 'remove'; path: string; value?: unknown }> = [];
  
  // Normalize old attributes (handle both route_ref/rutenummer and name/rutenavn)
  const normalizedOld: SegmentAttributes = {
    ...oldAttrs,
    rutenummer: oldAttrs.rutenummer || oldAttrs.route_ref as string,
    rutenavn: oldAttrs.rutenavn || oldAttrs.name as string,
  };
  
  // Fields to check (common segment attributes)
  const fieldsToCheck = ['rutenummer', 'rutenavn', 'vedlikeholdsansvarlig', 'rutetype', 'gradering'];
  
  // Also check for any other keys in newAttrs that aren't in the standard list
  const allKeys = new Set([...Object.keys(normalizedOld), ...Object.keys(newAttrs)]);
  
  for (const key of allKeys) {
    // Skip internal fields and normalized duplicates
    if (key === 'route_ref' || key === 'name' || key === 'op' || key === 'id' || key === 'objid') {
      continue;
    }
    
    const oldValue = normalizedOld[key];
    const newValue = newAttrs[key];

    if (oldValue === undefined && newValue !== undefined && newValue !== '') {
      // Add new attribute
      patch.push({ op: 'add', path: `/${key}`, value: newValue });
    } else if (oldValue !== undefined && (newValue === undefined || newValue === '')) {
      // Remove attribute (only for standard fields, not all fields)
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

export function SegmentEditForm({
  changeset,
  segmentId,
  currentAttributes = {},
  onSave,
  onCancel,
  onEventAdded,
}: SegmentEditFormProps) {
  const [attributes, setAttributes] = useState<SegmentAttributes>(currentAttributes);
  const [isSaving, setIsSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Update form when currentAttributes change
  useEffect(() => {
    // Normalize attribute names (handle both route_ref/rutenummer and name/rutenavn)
    const normalized: SegmentAttributes = {
      ...currentAttributes,
      rutenummer: currentAttributes.rutenummer || currentAttributes.route_ref as string || '',
      rutenavn: currentAttributes.rutenavn || currentAttributes.name as string || '',
    };
    // Remove the alternative field names to avoid duplicates
    if (normalized.route_ref && !normalized.rutenummer) {
      delete normalized.route_ref;
    }
    if (normalized.name && !normalized.rutenavn) {
      delete normalized.name;
    }
    setAttributes(normalized);
    setErrors({});
  }, [currentAttributes, segmentId]);

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

    // Normalize current attributes for comparison
    const normalizedCurrent: SegmentAttributes = {
      ...currentAttributes,
      rutenummer: currentAttributes.rutenummer || currentAttributes.route_ref as string || '',
      rutenavn: currentAttributes.rutenavn || currentAttributes.name as string || '',
    };
    
    // Generate JSON Patch
    const patch = generatePatch(normalizedCurrent, attributes);

    if (patch.length === 0) {
      notificationManager.info('Ingen endringer å lagre');
      onCancel();
      return;
    }

    setIsSaving(true);
    try {
      const event: SegmentUpdateAttrsEvent = {
        type: 'segment.update_attrs',
        target: { kind: 'segment', id: segmentId },
        patch,
      };

      if (changeset) {
        // Add event to existing changeset
        await api.addEvent(changeset.id, event);
        notificationManager.success('Segmentmetadata oppdatert');
      } else if (onEventAdded) {
        // Add to localEvents (no changeset yet)
        onEventAdded(event);
        notificationManager.success('Segmentmetadata oppdatert (ulagret)');
      } else {
        throw new Error('Ingen changeset eller onEventAdded callback tilgjengelig');
      }
      
      onSave();
    } catch (error: unknown) {
      const appError = handleApiError(error, 'Update Segment Attributes');
      notificationManager.error(`Kunne ikke oppdatere metadata: ${appError.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <form className="segment-edit-form" onSubmit={handleSubmit}>
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
        <button type="submit" className="btn btn-primary" disabled={isSaving}>
          {isSaving ? 'Lagrer...' : 'Lagre'}
        </button>
      </div>
    </form>
  );
}
