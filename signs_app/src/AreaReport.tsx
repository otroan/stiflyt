import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type {
  AreaStatsResponse,
  CandidatesResponse,
  RouteSummary,
  SignSite,
} from "./types";

interface Props {
  areaCode: string;
  candidates: CandidatesResponse | null;
  routeSummaries: Map<string, RouteSummary>;
  onClose: () => void;
}

interface PerRoute {
  rutenummer: string;
  rutenavn: string | null;
  length_km: number | null;
  n_sites: number;
  n_panels: number;
}

export default function AreaReport({ areaCode, candidates, routeSummaries, onClose }: Props) {
  const [stats, setStats] = useState<AreaStatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.getAreaStats(areaCode)
      .then((s) => { if (!cancelled) setStats(s); })
      .catch((e) => { if (!cancelled) setError(String((e as Error)?.message ?? e)); });
    return () => { cancelled = true; };
  }, [areaCode]);

  const aggregated = useMemo(() => aggregate(candidates, routeSummaries), [candidates, routeSummaries]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "white", borderRadius: 6, padding: 20,
          minWidth: 520, maxWidth: 720, maxHeight: "85vh", overflow: "auto",
          boxShadow: "0 4px 20px rgba(0,0,0,0.3)",
          font: "13px system-ui, sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Om området — {areaCode}</h2>
          <div style={{ flex: 1 }} />
          <button onClick={onClose} style={{ padding: "4px 10px" }}>Lukk</button>
        </div>

        {error && <div style={{ color: "#c43d3d", marginBottom: 8 }}>Feil: {error}</div>}

        <Headline stats={stats} agg={aggregated} />

        <h3 style={{ marginTop: 18, marginBottom: 6, fontSize: 14 }}>Skiltsteder</h3>
        <StatusBreakdown candidates={candidates} />

        <h3 style={{ marginTop: 18, marginBottom: 6, fontSize: 14 }}>Paneler</h3>
        <PanelBreakdown candidates={candidates} />

        <h3 style={{ marginTop: 18, marginBottom: 6, fontSize: 14 }}>
          Per rute ({aggregated.perRoute.length})
        </h3>
        <PerRouteTable rows={aggregated.perRoute} />

        {stats && (
          <div style={{ marginTop: 12, fontSize: 11, color: "#666" }}>
            Distanser er korrigert med faktor ×{stats.distance_correction_factor.toFixed(3)} og avrundet
            etter skiltspesifikasjonen (under 10 km nedover til 0,5 km; over 10 km til nærmeste hele km).
          </div>
        )}
      </div>
    </div>
  );
}

function Headline({ stats, agg }: { stats: AreaStatsResponse | null; agg: AggResult }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8 }}>
      <Tile label="Ruter" value={stats ? String(stats.total_routes) : "—"} />
      <Tile
        label="Merket sti (unik)"
        value={stats ? `${stats.unique_trail_length_km_displayed} km` : "—"}
        hint={stats ? `${Math.round(stats.unique_trail_length_m).toLocaleString("no")} m rå` : undefined}
      />
      <Tile label="Skiltsteder (aksept.)" value={String(agg.n_sites_accepted)} hint={`${agg.n_sites_proposed} foreslått`} />
      <Tile label="Paneler (aksept.)" value={String(agg.n_panels_accepted)} />
    </div>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div style={{ background: "#f5f5f5", borderRadius: 4, padding: "8px 10px" }}>
      <div style={{ fontSize: 11, color: "#666" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600, lineHeight: 1.2 }}>{value}</div>
      {hint && <div style={{ fontSize: 11, color: "#888" }}>{hint}</div>}
    </div>
  );
}

function StatusBreakdown({ candidates }: { candidates: CandidatesResponse | null }) {
  if (!candidates) return <div style={{ color: "#888" }}>Laster…</div>;
  const t = candidates.totals;
  const rows: [string, number][] = [
    ["Foreslått", t.proposed ?? 0],
    ["Akseptert", t.accepted ?? 0],
    ["Installert", t.installed ?? 0],
    ["Avvist", t.rejected ?? 0],
  ];
  return (
    <div style={{ display: "flex", gap: 8 }}>
      {rows.map(([k, n]) => (
        <div key={k} style={{ background: "#f5f5f5", padding: "4px 10px", borderRadius: 4 }}>
          <span style={{ color: "#666" }}>{k}: </span><strong>{n}</strong>
        </div>
      ))}
    </div>
  );
}

function PanelBreakdown({ candidates }: { candidates: CandidatesResponse | null }) {
  if (!candidates) return <div style={{ color: "#888" }}>Laster…</div>;
  let trehvit = 0, gronn = 0;
  for (const s of candidates.sites) {
    if (s.status !== "accepted" && s.status !== "installed") continue;
    for (const p of s.panels) {
      if (p.color === "grønn") gronn += 1; else trehvit += 1;
    }
  }
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <div style={{ background: "#f5efe0", padding: "4px 10px", borderRadius: 4, border: "1px solid #c4a44a" }}>
        <span style={{ color: "#6b4f00" }}>Trehvit: </span><strong>{trehvit}</strong>
      </div>
      <div style={{ background: "#1f6b3a", padding: "4px 10px", borderRadius: 4, color: "white" }}>
        Grønn: <strong>{gronn}</strong>
      </div>
    </div>
  );
}

function PerRouteTable({ rows }: { rows: PerRoute[] }) {
  const [sortBy, setSortBy] = useState<"rute" | "lengde" | "skilt" | "paneler">("rute");
  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      if (sortBy === "lengde") return (b.length_km ?? 0) - (a.length_km ?? 0);
      if (sortBy === "skilt") return b.n_sites - a.n_sites;
      if (sortBy === "paneler") return b.n_panels - a.n_panels;
      return a.rutenummer.localeCompare(b.rutenummer);
    });
    return copy;
  }, [rows, sortBy]);
  return (
    <div style={{ maxHeight: 360, overflow: "auto", border: "1px solid #eee", borderRadius: 4 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead style={{ position: "sticky", top: 0, background: "#fafafa" }}>
          <tr>
            <Th sort={sortBy} k="rute" onClick={() => setSortBy("rute")}>Rute</Th>
            <th style={thStyle}>Navn</th>
            <Th sort={sortBy} k="lengde" onClick={() => setSortBy("lengde")} align="right">km</Th>
            <Th sort={sortBy} k="skilt" onClick={() => setSortBy("skilt")} align="right">Skilt</Th>
            <Th sort={sortBy} k="paneler" onClick={() => setSortBy("paneler")} align="right">Paneler</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.rutenummer} style={{ borderTop: "1px solid #eee" }}>
              <td style={tdStyle}><strong>{r.rutenummer}</strong></td>
              <td style={tdStyle}>{r.rutenavn ?? <span style={{ color: "#aaa" }}>—</span>}</td>
              <td style={{ ...tdStyle, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                {r.length_km != null ? r.length_km.toFixed(1) : "—"}
              </td>
              <td style={{ ...tdStyle, textAlign: "right" }}>{r.n_sites}</td>
              <td style={{ ...tdStyle, textAlign: "right" }}>{r.n_panels}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const thStyle: React.CSSProperties = { textAlign: "left", padding: "6px 8px", fontWeight: 600, fontSize: 11, color: "#555" };
const tdStyle: React.CSSProperties = { padding: "4px 8px" };

function Th({
  children, sort, k, onClick, align,
}: {
  children: React.ReactNode;
  sort: string;
  k: string;
  onClick: () => void;
  align?: "left" | "right";
}) {
  const active = sort === k;
  return (
    <th
      onClick={onClick}
      style={{
        ...thStyle,
        textAlign: align ?? "left",
        cursor: "pointer",
        color: active ? "#1a7fc4" : thStyle.color,
        userSelect: "none",
      }}
    >
      {children}{active ? " ↓" : ""}
    </th>
  );
}

interface AggResult {
  n_sites_accepted: number;
  n_sites_proposed: number;
  n_panels_accepted: number;
  perRoute: PerRoute[];
}

function aggregate(
  candidates: CandidatesResponse | null,
  routeSummaries: Map<string, RouteSummary>,
): AggResult {
  const perRouteMap = new Map<string, PerRoute>();
  // Seed from route summaries so every known route shows up even with zero signs.
  for (const [rn, rs] of routeSummaries) {
    perRouteMap.set(rn, {
      rutenummer: rn,
      rutenavn: rs.rutenavn ?? null,
      length_km: rs.length_km_displayed ?? null,
      n_sites: 0,
      n_panels: 0,
    });
  }
  let n_sites_accepted = 0, n_sites_proposed = 0, n_panels_accepted = 0;
  if (candidates) {
    for (const s of candidates.sites) {
      if (s.status === "accepted" || s.status === "installed") n_sites_accepted += 1;
      else if (s.status === "proposed") n_sites_proposed += 1;
      const counts = countsForSite(s);
      // Each route this sign serves gets +1 sign and +panels.
      const routes = (s.route_numbers && s.route_numbers.length > 0)
        ? s.route_numbers
        : (s.rutenummer ? [s.rutenummer] : []);
      for (const r of routes) {
        let row = perRouteMap.get(r);
        if (!row) {
          row = { rutenummer: r, rutenavn: null, length_km: null, n_sites: 0, n_panels: 0 };
          perRouteMap.set(r, row);
        }
        if (s.status === "accepted" || s.status === "installed") {
          row.n_sites += 1;
          row.n_panels += counts.panels;
        }
      }
      if (s.status === "accepted" || s.status === "installed") {
        n_panels_accepted += counts.panels;
      }
    }
  }
  return {
    n_sites_accepted,
    n_sites_proposed,
    n_panels_accepted,
    perRoute: Array.from(perRouteMap.values()),
  };
}

function countsForSite(s: SignSite): { panels: number } {
  return { panels: s.panels.length };
}
