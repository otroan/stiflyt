/**
 * Sign site popup: list all destinations as separate skilt; edit retning, status, farge, km per destinasjon.
 */
import { useState, useEffect } from 'react';
import type { SignReportItem, SignDestination, DestinationSkilt } from '../types';
import { api } from '../api/client';
import { handleApiError } from '../utils/errorHandler';
import { notificationManager } from '../utils/notifications';

function formatDistanceKm(distanceMeters?: number | null): string {
  if (distanceMeters === undefined || distanceMeters === null) return '';
  const km = distanceMeters / 1000;
  if (km > 5) return `${Math.round(km)}km`;
  return `${(Math.round(km * 2) / 2).toFixed(1)}km`;
}

function effectiveDistanceM(dest: SignDestination): number | null | undefined {
  const ov = dest.skilt?.distance_meters;
  if (ov !== undefined && ov !== null) return ov;
  return dest.distance_meters;
}

function normalizeSkilt(sk?: DestinationSkilt | null): DestinationSkilt {
  return sk ?? { id: null, direction: null, status: null, skiltfarge: null, distance_meters: null };
}

export interface SignPopupContentProps {
  sign: SignReportItem;
  routeNumber: string | null;
  onSignsReload?: () => void;
  onClose: () => void;
  selectedSignDestinations?: Set<string>;
  onSignDestinationSelect?: (destKey: string, selected: boolean) => void;
  onEditAnchorName?: () => void;
}

export function SignPopupContent({
  sign,
  routeNumber,
  onSignsReload,
  onClose,
  selectedSignDestinations = new Set(),
  onSignDestinationSelect,
  onEditAnchorName,
}: SignPopupContentProps) {
  const [editingAnchorId, setEditingAnchorId] = useState<number | null>(null);
  const [editDirection, setEditDirection] = useState('');
  const [editStatus, setEditStatus] = useState('');
  const [editSkiltfarge, setEditSkiltfarge] = useState('');
  const [editDistanceM, setEditDistanceM] = useState('');
  const [useCustomDistance, setUseCustomDistance] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isUpdatingDestinations, setIsUpdatingDestinations] = useState(false);
  const [addAnchorId, setAddAnchorId] = useState('');
  const [registerOpen, setRegisterOpen] = useState(false);

  const destinations = sign.destinations ?? [];
  const signKey = String(sign.sign_site_id ?? sign.anchor_node_id ?? '');
  const signName = sign.name ?? sign.skiltstedidentifikator ?? `Skilt ${signKey}`;
  const signType = sign.is_endpoint ? 'Endepunkt' : sign.is_junction ? 'Kryss' : 'Node';

  useEffect(() => {
    if (editingAnchorId == null) return;
    const dest = destinations.find((d) => d.anchor_node_id === editingAnchorId);
    if (!dest) return;
    const sk = normalizeSkilt(dest.skilt);
    setEditDirection(sk.direction ?? '');
    setEditStatus(sk.status ?? '');
    setEditSkiltfarge(sk.skiltfarge ?? sign.skiltfarge ?? '');
    const ov = sk.distance_meters;
    setUseCustomDistance(ov !== undefined && ov !== null);
    setEditDistanceM(ov !== undefined && ov !== null ? String(Math.round(ov)) : '');
  }, [editingAnchorId, sign.skiltfarge, destinations]);

  const startEditDest = (dest: SignDestination) => {
    setEditingAnchorId(dest.anchor_node_id);
  };

  const cancelEditDest = () => {
    setEditingAnchorId(null);
  };

  const saveDestSkilt = async (anchorId: number) => {
    if (sign.sign_site_id == null) return;
    setIsSaving(true);
    try {
      let distanceM: number | null = null;
      if (useCustomDistance && editDistanceM.trim() !== '') {
        const n = parseFloat(editDistanceM.replace(',', '.'));
        if (!Number.isNaN(n)) distanceM = n;
      }
      const payload = {
        direction: editDirection.trim() || null,
        status: editStatus.trim() || null,
        skiltfarge: editSkiltfarge.trim() || null,
        distance_meters: distanceM,
      };
      await api.patchSignDestinationSkilt(sign.sign_site_id, anchorId, payload);
      notificationManager.success('Skilt lagret');
      setEditingAnchorId(null);
      onSignsReload?.();
    } catch (error) {
      notificationManager.error(handleApiError(error, 'Lagre skilt').message);
    } finally {
      setIsSaving(false);
    }
  };

  const effectiveRoute = routeNumber || sign.rutenummer_list?.[0];

  const registerSignSite = async () => {
    if (!effectiveRoute || !sign.coordinates || sign.coordinates.length < 2) return;
    const [lon, lat] = sign.coordinates;
    if (lon == null || lat == null) return;
    setIsSaving(true);
    try {
      await api.createSignSite(effectiveRoute, { lon: Number(lon), lat: Number(lat) });
      notificationManager.success('Skiltsted registrert');
      setRegisterOpen(false);
      onSignsReload?.();
    } catch (error) {
      notificationManager.error(handleApiError(error, 'Registrer skiltsted').message);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div style={{ minWidth: 260, maxWidth: 340 }} onClick={(e) => e.stopPropagation()} role="presentation">
      <strong>{signName}</strong>
      <br />
      <small style={{ color: '#666' }}>
        {signType} {sign.anchor_node_id != null ? `(${sign.anchor_node_id})` : ''}
      </small>

      {onEditAnchorName != null && (
        <div style={{ marginTop: 8 }}>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onClose();
              onEditAnchorName();
            }}
            style={{
              padding: '6px 10px',
              fontSize: '0.85em',
              width: '100%',
              border: '1px solid #ccc',
              borderRadius: 4,
              background: '#fafafa',
              cursor: 'pointer',
            }}
          >
            Ankernavn og stedsnavn…
          </button>
        </div>
      )}

      {sign.sign_site_id == null && (
        <div style={{ marginTop: 10, fontSize: '0.9em' }}>
          {!registerOpen ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setRegisterOpen(true);
              }}
              style={{ padding: '6px 10px', cursor: 'pointer' }}
            >
              Registrer skiltsted på ruten
            </button>
          ) : (
            <div>
              <p style={{ margin: '0 0 6px 0', color: '#555' }}>Oppretter skiltsted på valgt rute og punkt.</p>
              <button type="button" disabled={isSaving} onClick={() => void registerSignSite()} style={{ marginRight: 8 }}>
                {isSaving ? 'Oppretter…' : 'Bekreft'}
              </button>
              <button type="button" disabled={isSaving} onClick={() => setRegisterOpen(false)}>
                Avbryt
              </button>
            </div>
          )}
        </div>
      )}

      <div style={{ marginTop: 12 }}>
        <strong style={{ fontSize: '0.95em' }}>Destinasjoner (skilt)</strong>
        <div style={{ marginTop: 6 }}>
          {destinations.length === 0 ? (
            <div style={{ color: '#999', fontSize: '0.9em' }}>Ingen destinasjoner</div>
          ) : (
            destinations.map((dest) => {
              const sk = normalizeSkilt(dest.skilt);
              const destKey = `${sign.anchor_node_id ?? sign.sign_site_id}-${dest.anchor_node_id}`;
              const isSelected = selectedSignDestinations.has(destKey);
              const isEditing = editingAnchorId === dest.anchor_node_id;
              const effM = effectiveDistanceM(dest);

              if (isEditing && sign.sign_site_id != null) {
                return (
                  <div
                    key={dest.anchor_node_id}
                    style={{
                      border: '1px solid #2196f3',
                      borderRadius: 6,
                      padding: 8,
                      marginBottom: 8,
                      background: '#f8fbff',
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: 6 }}>{dest.name}</div>
                    <label style={{ display: 'block', fontSize: '0.8em', fontWeight: 600 }}>Pilretning</label>
                    <select
                      value={editDirection}
                      onChange={(e) => setEditDirection(e.target.value)}
                      style={{ width: '100%', marginBottom: 6, padding: 4 }}
                    >
                      <option value="">— Velg —</option>
                      <option value="Høyre">Høyre</option>
                      <option value="Venstre">Venstre</option>
                    </select>
                    <label style={{ display: 'block', fontSize: '0.8em', fontWeight: 600 }}>Status</label>
                    <select
                      value={editStatus}
                      onChange={(e) => setEditStatus(e.target.value)}
                      style={{ width: '100%', marginBottom: 6, padding: 4 }}
                    >
                      <option value="">— Velg —</option>
                      <option value="OK">OK</option>
                      <option value="Skadet">Skadet</option>
                      <option value="Mangler">Mangler</option>
                      <option value="Annet">Annet</option>
                    </select>
                    <label style={{ display: 'block', fontSize: '0.8em', fontWeight: 600 }}>Skiltfarge</label>
                    <select
                      value={editSkiltfarge}
                      onChange={(e) => setEditSkiltfarge(e.target.value)}
                      style={{ width: '100%', marginBottom: 6, padding: 4 }}
                    >
                      <option value="">— Standard (skiltsted) —</option>
                      <option value="grønn">Grønn</option>
                      <option value="trehvit">Trehvit</option>
                    </select>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.85em', marginBottom: 4 }}>
                      <input
                        type="checkbox"
                        checked={useCustomDistance}
                        onChange={(e) => setUseCustomDistance(e.target.checked)}
                      />
                      Egendefinert avstand (meter)
                    </label>
                    {useCustomDistance && (
                      <input
                        type="text"
                        inputMode="decimal"
                        placeholder="Meter"
                        value={editDistanceM}
                        onChange={(e) => setEditDistanceM(e.target.value)}
                        style={{ width: '100%', marginBottom: 8, padding: 4, boxSizing: 'border-box' }}
                      />
                    )}
                    <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                      <button type="button" disabled={isSaving} onClick={cancelEditDest}>
                        Avbryt
                      </button>
                      <button
                        type="button"
                        disabled={isSaving}
                        onClick={() => void saveDestSkilt(dest.anchor_node_id)}
                        style={{ background: '#4caf50', color: '#fff', border: 'none', borderRadius: 4, padding: '4px 10px' }}
                      >
                        {isSaving ? 'Lagrer…' : 'Lagre'}
                      </button>
                    </div>
                  </div>
                );
              }

              return (
                <div
                  key={dest.anchor_node_id}
                  style={{
                    border: '1px solid #e0e0e0',
                    borderRadius: 6,
                    padding: 8,
                    marginBottom: 6,
                    background: isSelected ? '#e3f2fd' : '#fafafa',
                  }}
                >
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => onSignDestinationSelect?.(destKey, !isSelected)}
                    onKeyDown={(e) => e.key === 'Enter' && onSignDestinationSelect?.(destKey, !isSelected)}
                    style={{ cursor: onSignDestinationSelect ? 'pointer' : 'default' }}
                  >
                    <strong>{isSelected ? '✓ ' : ''}{dest.name}</strong>
                    <div style={{ fontSize: '0.85em', color: '#555', marginTop: 2 }}>
                      Avstand: {formatDistanceKm(effM)}
                      {sk.distance_meters != null ? ' (egendefinert)' : ''}
                    </div>
                    <div style={{ fontSize: '0.85em', color: '#555' }}>
                      Retning: {sk.direction ?? '—'} · Status: {sk.status ?? '—'} · Farge: {sk.skiltfarge ?? sign.skiltfarge ?? '—'}
                    </div>
                  </div>
                  {sign.sign_site_id != null && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        startEditDest(dest);
                      }}
                      style={{
                        marginTop: 6,
                        padding: '4px 10px',
                        fontSize: '0.85em',
                        background: '#2196f3',
                        color: '#fff',
                        border: 'none',
                        borderRadius: 4,
                        cursor: 'pointer',
                      }}
                    >
                      Rediger skilt
                    </button>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {sign.sign_site_id != null && (
        <div style={{ marginTop: 12, borderTop: '1px solid #eee', paddingTop: 10 }}>
          <strong style={{ fontSize: '0.85em' }}>Administrer destinasjonsliste</strong>
          <div style={{ maxHeight: 100, overflowY: 'auto', marginTop: 4 }}>
            {(sign.destinations ?? []).map((d) => (
              <div
                key={d.anchor_node_id}
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8em', marginBottom: 4 }}
              >
                <span>{d.name}</span>
                <button
                  type="button"
                  disabled={isUpdatingDestinations}
                  onClick={async () => {
                    const next = (sign.destinations ?? []).filter((x) => x.anchor_node_id !== d.anchor_node_id);
                    setIsUpdatingDestinations(true);
                    try {
                      await api.setSignSiteDestinations(sign.sign_site_id!, {
                        destinations: next.map((x, i) => ({ anchor_node_id: x.anchor_node_id, display_order: i })),
                      });
                      onSignsReload?.();
                    } catch (err) {
                      notificationManager.error(handleApiError(err, 'Fjern destinasjon').message);
                    } finally {
                      setIsUpdatingDestinations(false);
                    }
                  }}
                  style={{ fontSize: '0.75em', padding: '2px 6px' }}
                >
                  Fjern
                </button>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
            <input
              type="number"
              placeholder="Anker-ID"
              value={addAnchorId}
              onChange={(e) => setAddAnchorId(e.target.value)}
              style={{ width: 88, padding: 4, fontSize: '0.85em' }}
              min={1}
            />
            <button
              type="button"
              disabled={isUpdatingDestinations || !addAnchorId.trim()}
              onClick={async () => {
                const id = parseInt(addAnchorId.trim(), 10);
                if (Number.isNaN(id) || id < 1) return;
                const current = sign.destinations ?? [];
                const next = [...current, { anchor_node_id: id, name: `Anchor ${id}`, distance_meters: null as number | null }];
                setIsUpdatingDestinations(true);
                setAddAnchorId('');
                try {
                  await api.setSignSiteDestinations(sign.sign_site_id!, {
                    destinations: next.map((x, i) => ({ anchor_node_id: x.anchor_node_id, display_order: i })),
                  });
                  onSignsReload?.();
                } catch (err) {
                  notificationManager.error(handleApiError(err, 'Legg til destinasjon').message);
                } finally {
                  setIsUpdatingDestinations(false);
                }
              }}
              style={{ padding: '4px 8px', fontSize: '0.85em' }}
            >
              Legg til destinasjon
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
