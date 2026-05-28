// Naismith's rule: 1 hour per 3 miles (4.828 km) on the map for the distance
// term, plus 10 minutes per 100 m of ascent for the climb term. Uses horizontal
// (2D) distance. Only meaningful when ascent is known (elevation resolved).
const KM_PER_HOUR = 4.828;          // 3 statute miles per hour
const MINUTES_PER_M_ASCENT = 0.1;   // 10 min per 100 m

export function naismithMinutes(distanceM: number, ascentM: number): number {
  return (distanceM / 1000 / KM_PER_HOUR) * 60 + ascentM * MINUTES_PER_M_ASCENT;
}

export function formatDuration(minutes: number): string {
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h} t ${m} min` : `${m} min`;
}

/** Naismith time string from a route's 2D length + ascent, or null if ascent
 *  is unknown (elevation not yet resolved). */
export function naismithLabel(
  lengthM: number | null | undefined,
  ascentM: number | null | undefined,
): string | null {
  if (lengthM == null || ascentM == null) return null;
  return formatDuration(naismithMinutes(lengthM, ascentM));
}
