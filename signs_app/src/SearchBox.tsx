import { useRef, useState } from "react";
import { Select } from "@mantine/core";
import { api } from "./api";
import type { PlaceSearchResult } from "./types";

const TYPE_LABEL: Record<string, string> = {
  ruteinfopunkt: "Rutepunkt",
  stedsnavn: "Stedsnavn",
  rute: "Rute",
};

/** Map search box (top bar). Debounced query against /search/places, which
 *  covers rutepunkt + stedsnavn + ruter. Picking a hit flies the map there
 *  (and, for routes, focuses the route) via `onSelect`. The Select is
 *  remounted via `key` after each pick so it clears for the next search. */
export default function SearchBox({ onSelect }: { onSelect: (r: PlaceSearchResult) => void }) {
  const [data, setData] = useState<{ value: string; label: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [remountKey, setRemountKey] = useState(0);
  const byId = useRef<Map<string, PlaceSearchResult>>(new Map());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = (q: string) => {
    if (timer.current) clearTimeout(timer.current);
    if (q.trim().length < 2) { setData([]); return; }
    timer.current = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await api.searchPlaces(q.trim(), 15);
        byId.current = new Map(res.results.map((r) => [r.id, r]));
        setData(res.results.map((r) => ({
          value: r.id,
          label: `${r.title}${r.subtitle ? ` · ${r.subtitle}` : ""} — ${TYPE_LABEL[r.type] ?? r.type}`,
        })));
      } catch {
        setData([]);
      } finally {
        setLoading(false);
      }
    }, 250);
  };

  return (
    <Select
      key={remountKey}
      searchable
      placeholder="Søk sted, rutepunkt, rute…"
      data={data}
      // Disable client-side filtering — the server already ranked the hits and
      // their labels may not literally contain the query string.
      filter={({ options }) => options}
      onSearchChange={search}
      nothingFoundMessage={loading ? "Søker…" : "Ingen treff"}
      onChange={(v) => {
        if (!v) return;
        const r = byId.current.get(v);
        if (r) onSelect(r);
        setData([]);
        setRemountKey((k) => k + 1);
      }}
      size="xs"
      w={260}
      comboboxProps={{ withinPortal: true }}
      aria-label="Søk på kartet"
    />
  );
}
