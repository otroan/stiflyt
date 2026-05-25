import type { SignPanel } from "./types";

export function formatKm(panel: SignPanel): string {
  const v = panel.distance_km_displayed;
  if (v == null) return "—";
  return v < 10 ? v.toFixed(1) : String(Math.round(v));
}
