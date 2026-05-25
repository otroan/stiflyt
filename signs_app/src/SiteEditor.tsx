import { useState } from "react";
import type { SignPanel, SignSite } from "./types";
import { formatKm } from "./format";
import { api } from "./api";
import NamePicker from "./NamePicker";

interface Props {
  site: SignSite;
  areaCode: string;
  onClose: () => void;
  onChanged: () => void;
  selectedPanels: Set<string>;
  onTogglePanel: (key: string) => void;
}

export default function SiteEditor({
  site,
  areaCode,
  onClose,
  onChanged,
  selectedPanels,
  onTogglePanel,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [editingName, setEditingName] = useState(false);

  const kind = site.is_manual
    ? `Manuelt skilt på ${site.rutenummer ?? "?"}`
    : site.is_endpoint && !site.is_junction
      ? "Endepunkt"
      : site.is_junction
        ? "Kryss"
        : "Skiltsted";

  async function doAccept() {
    if (site.anchor_node_id == null) return;
    setBusy(true); setErr(null);
    try { await api.acceptCandidate(areaCode, site.anchor_node_id); onChanged(); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  }

  async function doReject() {
    if (site.anchor_node_id == null) return;
    setBusy(true); setErr(null);
    try { await api.rejectCandidate(areaCode, site.anchor_node_id); onChanged(); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  }

  async function doDelete() {
    if (site.sign_site_id == null) return;
    const label = site.site_code ? `Slett ${site.site_code}` : `Slett skiltet "${site.name || ""}"`;
    // Different consequences for manual vs anchor-based signs — be honest in the prompt.
    const consequence = site.is_manual
      ? "Skiltet og alle panel-redigeringer blir borte for godt."
      : "Skiltstedet går tilbake til foreslått kandidat. Aksepter-redigeringer (farge, pilretning osv.) går tapt.";
    if (!window.confirm(`${label}?\n\n${consequence}`)) return;
    setBusy(true); setErr(null);
    try { await api.deleteSite(site.sign_site_id); onClose(); onChanged(); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); }
    finally { setBusy(false); }
  }

  async function saveAnchorName(newName: string) {
    if (site.anchor_node_id == null) {
      setErr("Manuelle skilt har ikke ankernavn å redigere ennå");
      return;
    }
    const v = newName.trim();
    if (!v) return;
    setBusy(true); setErr(null);
    try { await api.setAnchorName(site.anchor_node_id, v); setEditingName(false); onChanged(); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); throw e; }
    finally { setBusy(false); }
  }

  async function saveManualSiteName(newName: string) {
    if (site.sign_site_id == null) return;
    const v = newName.trim();
    if (!v) return;
    setBusy(true); setErr(null);
    try { await api.updateSiteName(site.sign_site_id, v); setEditingName(false); onChanged(); }
    catch (e) { setErr(String((e as Error)?.message ?? e)); throw e; }
    finally { setBusy(false); }
  }

  /** Implicit accept: panel edits require a sign_site_id. If the site is only
   *  a candidate, accept it transparently so the user doesn't have to click
   *  Aksepter first. Returns the resolved sign_site_id or null on failure. */
  async function ensureAccepted(): Promise<number | null> {
    if (site.sign_site_id != null) return site.sign_site_id;
    if (site.anchor_node_id == null) {
      setErr("Kan ikke redigere før skiltet er akseptert (ingen ankernode)");
      return null;
    }
    setErr(null);
    try {
      const res = await api.acceptCandidate(areaCode, site.anchor_node_id);
      onChanged();
      return res.id;
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
      return null;
    }
  }

  async function patchPanel(
    panel: SignPanel,
    patch: { color?: "trehvit" | "grønn"; direction?: string | null; distance_km?: number | null; destination_name?: string | null },
  ) {
    if (panel.destination_anchor_node_id == null) return;
    setBusy(true); setErr(null);
    try {
      const siteId = await ensureAccepted();
      if (siteId == null) return;
      await api.patchPanel(siteId, panel.destination_anchor_node_id, {
        ...patch,
        // Always send the panel's first_link_id so parallel-path siblings
        // (same destination anchor, different physical out-link) don't share
        // a storage row. Null = the legacy no-discriminator slot.
        first_link_id: panel.first_link_id ?? null,
      });
      onChanged();
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    } finally { setBusy(false); }
  }

  return (
    <div className="site-card">
      <div className="site-header">
        <h3
          onClick={() => setEditingName(true)}
          title="Klikk for å endre navn"
          style={{ cursor: "pointer" }}
        >
          {site.name || "(uten navn)"}
          <span style={{ fontSize: 12, color: "#888" }}> ✎</span>
        </h3>
      </div>
      {editingName && site.anchor_node_id != null && (
        <NamePicker
          loadCandidates={() => api.getAnchorPlacenames(site.anchor_node_id!)}
          save={saveAnchorName}
          initialName={site.name || ""}
          onCancel={() => setEditingName(false)}
        />
      )}
      {editingName && site.anchor_node_id == null && site.lon != null && site.lat != null && (
        <NamePicker
          loadCandidates={() => api.getPlacenamesNearby(site.lon!, site.lat!)}
          save={saveManualSiteName}
          initialName={site.name || ""}
          onCancel={() => setEditingName(false)}
          manualPlaceholder="Eget navn på det manuelle skiltet…"
        />
      )}
      <div className="meta">
        {site.site_code && <strong>{site.site_code} · </strong>}
        {kind} · {site.anchor_node_id != null ? `ankernode ${site.anchor_node_id}` : "punkt"} · {site.route_numbers.join(", ") || "ingen ruter"}
      </div>

      <div className="back-text">{site.back_text || "(ingen baksidetekst)"}</div>

      <div>
        {site.panels.length === 0 && <div className="empty" style={{ padding: 8 }}>Ingen destinasjoner</div>}
        {site.panels.map((p) => (
          <PanelRow
            key={panelKey(p)}
            panel={p}
            siteId={site.sign_site_id}
            selectedPanels={selectedPanels}
            onTogglePanel={onTogglePanel}
            onSave={(patch) => patchPanel(p, patch)}
            busy={busy}
          />
        ))}
      </div>

      {err && <div style={{ color: "#a32d2d", fontSize: 12, marginTop: 6 }}>{err}</div>}

      <div className="actions">
        {!site.is_manual && site.status !== "accepted" && site.status !== "installed" && (
          <button className="primary" onClick={doAccept} disabled={busy || site.anchor_node_id == null}>
            Aksepter
          </button>
        )}
        {!site.is_manual && site.status !== "rejected" && (
          <button className="danger" onClick={doReject} disabled={busy || site.anchor_node_id == null}>
            Avvis
          </button>
        )}
        {site.sign_site_id != null && (
          <button className="danger" onClick={doDelete} disabled={busy} title="Slett raden i databasen">
            Slett
          </button>
        )}
        <button onClick={onClose}>Lukk</button>
      </div>
    </div>
  );
}

function panelKey(p: SignPanel): string {
  return `${p.destination_name}::${p.destination_anchor_node_id ?? ""}::${p.first_link_id ?? ""}`;
}

function selectionKey(siteId: number, anchorId: number, firstLinkId: number | null | undefined): string {
  // 3-part key: parallel-path panels share (site, anchor) but differ on first_link_id.
  return `${siteId}:${anchorId}:${firstLinkId ?? ""}`;
}

interface PanelRowProps {
  panel: SignPanel;
  siteId: number | null;
  selectedPanels: Set<string>;
  onTogglePanel: (key: string) => void;
  onSave: (patch: { color?: "trehvit" | "grønn"; direction?: string | null; distance_km?: number | null; destination_name?: string | null }) => Promise<void>;
  busy: boolean;
}

function PanelRow({ panel, siteId, selectedPanels, onTogglePanel, onSave, busy }: PanelRowProps) {
  const [open, setOpen] = useState(false);
  const [nameDraft, setNameDraft] = useState(panel.destination_name);
  const [kmDraft, setKmDraft] = useState<string>(panel.distance_km_displayed != null ? String(panel.distance_km_displayed) : "");
  const [direction, setDirection] = useState<string>(panel.direction || "");

  const canSelect = siteId != null && panel.destination_anchor_node_id != null;
  const selKey = canSelect
    ? selectionKey(siteId!, panel.destination_anchor_node_id!, panel.first_link_id ?? null)
    : "";
  const checked = canSelect && selectedPanels.has(selKey);

  async function toggleColor() {
    const next = panel.color === "grønn" ? "trehvit" : "grønn";
    await onSave({ color: next });
  }

  async function saveAll() {
    const patch: { color?: "trehvit" | "grønn"; direction?: string | null; distance_km?: number | null; destination_name?: string | null } = {};
    if (nameDraft && nameDraft !== panel.destination_name) patch.destination_name = nameDraft;
    if (direction !== (panel.direction || "")) patch.direction = direction || null;
    const km = kmDraft.trim() ? Number(kmDraft) : null;
    if (km !== panel.distance_km_displayed) patch.distance_km = km;
    if (Object.keys(patch).length === 0) { setOpen(false); return; }
    await onSave(patch);
    setOpen(false);
  }

  return (
    <div className="panel-row" title={panel.route_numbers.join(", ")}
      style={{ display: "grid", gridTemplateColumns: "22px 1fr 60px 80px 28px", alignItems: "center", gap: 6, padding: "6px 0", borderTop: "1px solid #eee" }}>
      <div>
        <input
          type="checkbox"
          checked={checked}
          disabled={!canSelect}
          onChange={() => canSelect && onTogglePanel(selKey)}
          title={canSelect ? "Velg for Excel-eksport" : "Aksepter skiltet for å kunne velge"}
        />
      </div>
      <div>
        <div className="dest">{panel.destination_name}</div>
        <div className="routes">{panel.route_numbers.join(", ")}{panel.direction ? ` · ↗ ${panel.direction}` : ""}</div>
      </div>
      <div className="km">{formatKm(panel)} km</div>
      <div className="color">
        <button
          className={`color-tag ${panel.color === "grønn" ? "gronn" : "tre"}`}
          onClick={toggleColor}
          disabled={busy}
          title="Bytt farge (aksepterer skiltet automatisk om nødvendig)"
          style={{ border: "1px solid", padding: "1px 5px", borderRadius: 3, cursor: "pointer", background: "none" }}
        >
          {panel.color}
        </button>
      </div>
      <div>
        <button
          disabled={busy}
          title="Rediger panel (aksepterer skiltet automatisk om nødvendig)"
          onClick={() => setOpen((v) => !v)}
          style={{ fontSize: 11 }}
        >
          ✎
        </button>
      </div>
      {open && (
        <div className="panel-edit" style={{ gridColumn: "1 / -1", background: "#fafafa", padding: 8, marginTop: 4, border: "1px solid #ddd", borderRadius: 4 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 80px 120px", gap: 6 }}>
            <label style={{ display: "flex", flexDirection: "column", fontSize: 11 }}>
              Destinasjon
              <input value={nameDraft} onChange={(e) => setNameDraft(e.target.value)} />
            </label>
            <label style={{ display: "flex", flexDirection: "column", fontSize: 11 }}>
              km
              <input type="number" step="0.5" value={kmDraft} onChange={(e) => setKmDraft(e.target.value)} />
            </label>
            <label style={{ display: "flex", flexDirection: "column", fontSize: 11 }}>
              Pilretning
              <select value={direction} onChange={(e) => setDirection(e.target.value)}>
                <option value="">—</option>
                <option value="venstre">venstre ←</option>
                <option value="rett fram">rett fram ↑</option>
                <option value="høyre">høyre →</option>
              </select>
            </label>
          </div>
          <div style={{ marginTop: 6, display: "flex", gap: 6, justifyContent: "flex-end" }}>
            <button onClick={() => setOpen(false)}>Avbryt</button>
            <button className="primary" onClick={saveAll}>Lagre</button>
          </div>
        </div>
      )}
    </div>
  );
}
