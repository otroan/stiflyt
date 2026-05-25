import { useEffect, useState } from "react";
import type { FacilityCandidate, PlacenameCandidate, PlacenameCandidatesResponse } from "./types";

interface Props {
  /** Fetch candidates (ruteinfopunkt + stedsnavn) for whatever location this picker covers. */
  loadCandidates: () => Promise<PlacenameCandidatesResponse>;
  /** Persist the chosen (or typed) name. Resolves on success. */
  save: (name: string) => Promise<void>;
  initialName: string;
  onCancel: () => void;
  /** Optional override of the manual-input placeholder. */
  manualPlaceholder?: string;
}

interface Loaded {
  facilities: FacilityCandidate[];
  candidates: PlacenameCandidate[];
}

/** Inline picker: nearest ruteinfopunkt + stedsnavn first, manual text as fallback.
 *  Works for both anchor-keyed names (writes to ops.endpoint_names) and
 *  manual-sign names (writes to ops.sign_sites.name) — the difference is
 *  injected via `loadCandidates` and `save`. */
export default function NamePicker({ loadCandidates, save, initialName, onCancel, manualPlaceholder }: Props) {
  const [draft, setDraft] = useState(initialName);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [data, setData] = useState<Loaded | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    loadCandidates()
      .then((r) => {
        if (cancelled) return;
        setData({ facilities: r.facilities || [], candidates: r.candidates || [] });
      })
      .catch((e) => !cancelled && setErr(String((e as Error)?.message ?? e)))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function pick(name: string) {
    setDraft(name);
    setBusy(true); setErr(null);
    try { await save(name); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  }

  async function saveDraft() {
    const v = draft.trim();
    if (!v) return;
    setBusy(true); setErr(null);
    try { await save(v); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="name-picker" style={{ background: "#fafafa", border: "1px solid #ddd", borderRadius: 4, padding: 8, marginBottom: 8 }}>
      {loading && <div style={{ fontSize: 12, color: "#888" }}>Søker etter nærliggende navn…</div>}
      {err && <div style={{ color: "#a32d2d", fontSize: 12, marginBottom: 6 }}>{err}</div>}

      {data && (
        <>
          {data.facilities.length > 0 && (
            <CandidateGroup
              title="Anlegg (ruteinfopunkt)"
              items={data.facilities.map((f) => ({ name: f.name, sub: facilitySubLabel(f), distance_meters: f.distance_meters }))}
              onPick={pick}
              disabled={busy}
            />
          )}
          {data.candidates.length > 0 && (
            <CandidateGroup
              title="Stedsnavn"
              items={data.candidates.map((c) => ({ name: c.name, sub: c.source_type, distance_meters: c.distance_meters }))}
              onPick={pick}
              disabled={busy}
            />
          )}
          {data.facilities.length === 0 && data.candidates.length === 0 && (
            <div style={{ fontSize: 12, color: "#888", padding: 4 }}>
              Ingen forslag innen 500 m. Skriv inn et navn manuelt under.
            </div>
          )}
        </>
      )}

      <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
        <input
          autoFocus
          placeholder={manualPlaceholder || "Skriv inn navn manuelt…"}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") saveDraft(); if (e.key === "Escape") onCancel(); }}
          style={{ flex: 1 }}
          disabled={busy}
        />
        <button onClick={saveDraft} disabled={busy || !draft.trim()} className="primary">Lagre</button>
        <button onClick={onCancel} disabled={busy}>Avbryt</button>
      </div>
    </div>
  );
}

function facilitySubLabel(f: FacilityCandidate): string {
  return f.tilrettelegging ? `ruteinfopunkt · ${f.tilrettelegging}` : "ruteinfopunkt";
}

interface RowItem { name: string; sub: string; distance_meters?: number | null }

function CandidateGroup({
  title,
  items,
  onPick,
  disabled,
}: {
  title: string;
  items: RowItem[];
  onPick: (name: string) => void;
  disabled: boolean;
}) {
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "#666", padding: "2px 0" }}>{title}</div>
      <div>
        {items.map((it, idx) => (
          <button
            key={`${it.name}-${idx}`}
            type="button"
            onClick={() => onPick(it.name)}
            disabled={disabled}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 56px",
              gap: 6,
              alignItems: "center",
              width: "100%",
              textAlign: "left",
              padding: "4px 8px",
              border: "1px solid #e2e2e2",
              borderRadius: 3,
              background: "white",
              cursor: disabled ? "not-allowed" : "pointer",
              marginBottom: 2,
              fontSize: 12,
            }}
          >
            <div>
              <div style={{ fontWeight: 500 }}>{it.name}</div>
              <div style={{ color: "#888", fontSize: 10 }}>{it.sub}</div>
            </div>
            <div style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", color: "#666" }}>
              {it.distance_meters != null ? `${Math.round(it.distance_meters)} m` : "—"}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
