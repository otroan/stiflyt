import { useMemo } from 'react';
import type { AnchorNodeInfo, PlacenameCandidate } from '../types';
import './AnchorNameDialog.css';

interface AnchorNameDialogProps {
  isOpen: boolean;
  anchor: AnchorNodeInfo | null;
  candidates: PlacenameCandidate[];
  selectedIndex: number | null;
  manualName: string;
  onSelectCandidate: (index: number | null) => void;
  onManualNameChange: (value: string) => void;
  onSave: () => void;
  onCancel: () => void;
}

export function AnchorNameDialog({
  isOpen,
  anchor,
  candidates,
  selectedIndex,
  manualName,
  onSelectCandidate,
  onManualNameChange,
  onSave,
  onCancel,
}: AnchorNameDialogProps) {
  const currentName = anchor?.name?.name;
  const anchorLabel = anchor ? `Anchor ${anchor.anchor_node_id}` : 'Anchor';

  const hasSelection = useMemo(() => {
    return manualName.trim().length > 0 || selectedIndex !== null;
  }, [manualName, selectedIndex]);

  if (!isOpen || !anchor) {
    return null;
  }

  return (
    <div className="anchor-name-dialog-overlay" onClick={onCancel}>
      <div className="anchor-name-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="anchor-name-dialog__header">
          <h3>{anchorLabel}</h3>
          <button className="anchor-name-dialog__close" onClick={onCancel} type="button">
            ×
          </button>
        </div>
        <div className="anchor-name-dialog__content">
          <div className="anchor-name-dialog__meta">
            <div>Koordinater: {anchor.coordinates[1].toFixed(6)}, {anchor.coordinates[0].toFixed(6)}</div>
            <div>Lenker: {anchor.link_count}</div>
            <div>Nåværende navn: {currentName || '—'}</div>
          </div>
          <div className="anchor-name-dialog__section">
            <div className="anchor-name-dialog__section-title">Forslag</div>
            {candidates.length === 0 && (
              <div className="anchor-name-dialog__empty">Ingen treff i radiusen.</div>
            )}
            {candidates.map((candidate, idx) => {
              const distance =
                typeof candidate.distance_meters === 'number'
                  ? `${candidate.distance_meters.toFixed(1)} m`
                  : 'ukjent';
              return (
                <label key={`${candidate.source_type}-${candidate.name}-${idx}`} className="anchor-name-dialog__option">
                  <input
                    type="radio"
                    name="anchor-candidate"
                    checked={selectedIndex === idx}
                    onChange={() => onSelectCandidate(idx)}
                  />
                  <span className="anchor-name-dialog__option-label">
                    {candidate.name} · {candidate.source_type} · {distance}
                  </span>
                </label>
              );
            })}
          </div>
          <div className="anchor-name-dialog__section">
            <div className="anchor-name-dialog__section-title">Manuelt navn</div>
            <input
              type="text"
              value={manualName}
              placeholder="Skriv inn navn"
              onChange={(e) => {
                onManualNameChange(e.target.value);
                if (e.target.value.trim().length > 0) {
                  onSelectCandidate(null);
                }
              }}
            />
          </div>
        </div>
        <div className="anchor-name-dialog__actions">
          <button type="button" onClick={onCancel} className="secondary">
            Avbryt
          </button>
          <button type="button" onClick={onSave} disabled={!hasSelection}>
            Lagre navn
          </button>
        </div>
      </div>
    </div>
  );
}
