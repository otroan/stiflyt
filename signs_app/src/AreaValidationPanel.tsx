import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Button, Card, Group, Loader, Stack, Text } from "@mantine/core";
import { IconRefresh } from "@tabler/icons-react";
import { api } from "./api";
import { notifyError } from "./notify";
import type { AreaValidationResponse } from "./types";

// Friendly Norwegian labels for the validator issue types surfaced in the list.
const ISSUE_LABEL_NB: Record<string, string> = {
  ROUTE_HAS_LOOP: "Sløyfe",
  ROUTE_DISCONNECTED: "Usammenhengende",
  ROUTE_HAS_BRANCHES: "Forgreininger",
  SEGMENT_GAP: "Segmentgap",
  MULTIPLE_LINK_COMPONENTS: "Flere deler",
  INCONSISTENT_RUTENAVN: "Ulikt rutenavn",
  INCONSISTENT_VEDLIKEHOLDSANSVARLIG: "Ulik ansvarlig",
  INCONSISTENT_RUTETYPE: "Ulik rutetype",
  INCONSISTENT_GRADERING: "Ulik gradering",
  RUTENAVN_UKJENT: "Rutenavn «Ukjent»",
  MISSING_RUTENAVN: "Mangler rutenavn",
  MISSING_RUTENAVN_SOME_SEGMENTS: "Mangler rutenavn (noen)",
  MISSING_VEDLIKEHOLDSANSVARLIG: "Mangler ansvarlig",
  MISSING_VEDLIKEHOLDSANSVARLIG_SOME_SEGMENTS: "Mangler ansvarlig (noen)",
  MISSING_REQUIRED_FIELDS: "Mangler påkrevd felt",
  DUPLICATE_RUTENUMMER_IN_SEGMENT: "Duplikat rutenummer",
  DUPLICATE_RUTENAVN_IN_SEGMENT: "Duplikat rutenavn",
  FERRY_SUSPECT: "Mistenkt båtrute",
};

function issueLabel(t: string): string {
  return ISSUE_LABEL_NB[t] ?? t;
}

function sinceText(iso: string | null): string {
  if (!iso) return "aldri";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "nå nettopp";
  if (mins < 60) return `for ${mins} min siden`;
  const h = Math.round(mins / 60);
  return `for ${h} t siden`;
}

export default function AreaValidationPanel({
  areaCode,
  onOpenRoute,
}: {
  areaCode: string;
  onOpenRoute: (rutenummer: string) => void;
}) {
  const [data, setData] = useState<AreaValidationResponse | null>(null);
  const pollRef = useRef<number | null>(null);

  const fetchOnce = useCallback(async (refresh = false) => {
    try {
      const r = await api.getAreaValidation(areaCode, refresh);
      setData(r);
      return r.status;
    } catch (e) {
      notifyError(e);
      return "error" as const;
    }
  }, [areaCode]);

  // Initial load + poll while the background compute runs.
  useEffect(() => {
    let cancelled = false;
    const clear = () => { if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; } };
    void fetchOnce().then((status) => {
      if (cancelled || status !== "computing") return;
      pollRef.current = window.setInterval(async () => {
        const s = await fetchOnce();
        if (s !== "computing") clear();
      }, 3000);
    });
    return () => { cancelled = true; clear(); };
  }, [fetchOnce]);

  const computing = data?.status === "computing";
  const routes = data?.routes ?? [];
  const problems = routes.filter((r) => r.status !== "OK");
  const okCount = routes.length - problems.length;

  return (
    <Stack gap="sm" p="sm">
      <Group justify="space-between" wrap="nowrap">
        <div>
          <Text fw={600}>Kvalitet · {areaCode}</Text>
          <Text size="xs" c="dimmed">
            {computing
              ? "Validerer alle ruter i området…"
              : data
                ? `${problems.length} med feil/advarsel · ${okCount} OK · validert ${sinceText(data.computed_at)}`
                : "Laster…"}
          </Text>
        </div>
        <Button
          size="xs"
          variant="light"
          leftSection={computing ? <Loader size={12} /> : <IconRefresh size={14} />}
          disabled={computing}
          onClick={() => fetchOnce(true)}
        >
          Oppdater
        </Button>
      </Group>

      {computing && routes.length === 0 && (
        <Group gap="xs"><Loader size="sm" /><Text size="sm" c="dimmed">Dette tar et par minutter…</Text></Group>
      )}

      {problems.map((r) => (
        <Card key={r.rutenummer} withBorder padding="xs" radius="sm"
          style={{ cursor: "pointer" }} onClick={() => onOpenRoute(r.rutenummer)}>
          <Group justify="space-between" wrap="nowrap" align="flex-start">
            <div style={{ flex: 1, minWidth: 0 }}>
              <Group gap={6} wrap="nowrap">
                <Badge size="xs" color={r.status === "ERROR" ? "red" : "yellow"} variant="filled">
                  {r.status}
                </Badge>
                <Text fw={500} size="sm">{r.rutenummer}</Text>
                {r.rutenavn && <Text size="xs" c="dimmed" truncate>· {r.rutenavn}</Text>}
              </Group>
              <Group gap={4} mt={4}>
                {r.issue_types.map((t) => (
                  <Badge key={t} size="xs" variant="light" color="gray">{issueLabel(t)}</Badge>
                ))}
              </Group>
            </div>
          </Group>
        </Card>
      ))}

      {!computing && data && problems.length === 0 && (
        <Text size="sm" c="dimmed">Ingen feil eller advarsler i området.</Text>
      )}
    </Stack>
  );
}
