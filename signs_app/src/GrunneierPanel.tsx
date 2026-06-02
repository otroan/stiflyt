import { ActionIcon, Alert, Badge, Button, Card, Code, Group, Loader, SegmentedControl, Stack, Text, Title, Tooltip } from "@mantine/core";
import { IconAlertTriangle, IconHomeDollar, IconInfoCircle, IconMapPin, IconRoute, IconUsers, IconX } from "@tabler/icons-react";
import type { GeometryOwnerItem, PointMatrikkelResponse } from "./types";

interface Props {
  /** "punkt" = Phase 2 point lookup, "lenker" = Phase 3 link selection. */
  mode: "punkt" | "lenker";
  onModeChange: (m: "punkt" | "lenker") => void;
  // Punkt mode
  result: PointMatrikkelResponse | null;
  loading: boolean;
  error: string | null;
  onClear: () => void;
  // Lenker mode
  selectedLinkCount: number;
  linkOwners: { items: GeometryOwnerItem[]; totalKm: number; linkCount: number; errorCount: number } | null;
  linkOwnersLoading: boolean;
  linkOwnersError: string | null;
  onFetchLinkOwners: () => void;
  onClearLinks: () => void;
  /** Hover an owner row -> spotlight its segment on the map (null on leave). */
  onHoverMatrikkel: (geometry: GeoJSON.Geometry | null) => void;
}

/** Grunneier sidebar — Phases 2 + 3.
 *
 *  A segmented control switches between two modes:
 *    - Punkt: every map click runs api.pointMatrikkelenhet(lat, lon); the
 *      matrikkel polygon renders on the map and the owner card here (Phase 2).
 *    - Lenker: the map shows a clickable network-link overlay; clicking links
 *      accumulates a selection, and "Hent eiere" batches the owner lookup over
 *      all selected links and renders a deduplicated owner list (Phase 3).
 */
export default function GrunneierPanel({
  mode,
  onModeChange,
  result,
  loading,
  error,
  onClear,
  selectedLinkCount,
  linkOwners,
  linkOwnersLoading,
  linkOwnersError,
  onFetchLinkOwners,
  onClearLinks,
  onHoverMatrikkel,
}: Props) {
  return (
    <Stack gap="md" p="md">
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Title order={4}>
          <IconHomeDollar size={18} style={{ verticalAlign: "middle", marginRight: 6 }} />
          Grunneier
        </Title>
        {mode === "punkt" && result && (
          <Tooltip label="Tøm valg">
            <ActionIcon size="sm" variant="subtle" color="gray" onClick={onClear}>
              <IconX size={14} />
            </ActionIcon>
          </Tooltip>
        )}
      </Group>

      <SegmentedControl
        value={mode}
        onChange={(v) => onModeChange(v as "punkt" | "lenker")}
        fullWidth
        size="xs"
        data={[
          { value: "punkt", label: "Punkt" },
          { value: "lenker", label: "Lenker" },
        ]}
      />

      {mode === "punkt" ? (
        <PunktMode result={result} loading={loading} error={error} />
      ) : (
        <LenkerMode
          selectedLinkCount={selectedLinkCount}
          linkOwners={linkOwners}
          loading={linkOwnersLoading}
          error={linkOwnersError}
          onFetch={onFetchLinkOwners}
          onClear={onClearLinks}
          onHoverMatrikkel={onHoverMatrikkel}
        />
      )}
    </Stack>
  );
}

function PunktMode({ result, loading, error }: { result: PointMatrikkelResponse | null; loading: boolean; error: string | null }) {
  return (
    <>
      {loading && (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="sm" c="dimmed">Slår opp matrikkelenhet…</Text>
        </Group>
      )}

      {!loading && !result && !error && (
        <Alert icon={<IconMapPin size={16} />} color="violet" variant="light">
          <Text size="sm">Klikk på kartet for å finne matrikkelenhet og eier.</Text>
        </Alert>
      )}

      {!loading && error && (
        <Alert icon={<IconInfoCircle size={16} />} color="gray" variant="light">
          <Text size="sm">{error}</Text>
        </Alert>
      )}

      {result && <MatrikkelDetails r={result} />}
    </>
  );
}

function LenkerMode({
  selectedLinkCount,
  linkOwners,
  loading,
  error,
  onFetch,
  onClear,
  onHoverMatrikkel,
}: {
  selectedLinkCount: number;
  linkOwners: { items: GeometryOwnerItem[]; totalKm: number; linkCount: number; errorCount: number } | null;
  loading: boolean;
  error: string | null;
  onFetch: () => void;
  onClear: () => void;
  onHoverMatrikkel: (geometry: GeoJSON.Geometry | null) => void;
}) {
  return (
    <>
      <Alert icon={<IconRoute size={16} />} color="violet" variant="light" p="xs">
        <Text size="sm">Klikk lenker på kartet for å velge dem. Valgte lenker blir grønne.</Text>
      </Alert>

      <Group gap="xs" justify="space-between">
        <Badge color={selectedLinkCount > 0 ? "violet" : "gray"} variant="light">
          {selectedLinkCount} {selectedLinkCount === 1 ? "lenke" : "lenker"} valgt
        </Badge>
        {selectedLinkCount > 0 && (
          <Button size="compact-xs" variant="subtle" color="gray" onClick={onClear}>
            Tøm valg
          </Button>
        )}
      </Group>

      <Button
        leftSection={<IconUsers size={16} />}
        color="violet"
        disabled={selectedLinkCount === 0}
        loading={loading}
        onClick={onFetch}
      >
        Hent eiere ({selectedLinkCount} lenker)
      </Button>

      {error && (
        <Alert icon={<IconAlertTriangle size={14} />} color="orange" variant="light" p="xs">
          <Text size="xs">{error}</Text>
        </Alert>
      )}

      {linkOwners && (
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            {linkOwners.items.length} matrikkelenheter · {linkOwners.totalKm.toFixed(2)} km
            {linkOwners.errorCount > 0 ? ` · ${linkOwners.errorCount} lenke(r) feilet` : ""}
          </Text>
          {linkOwners.items.length === 0 ? (
            <Text size="sm" c="dimmed">Ingen matrikkelenheter funnet langs de valgte lenkene.</Text>
          ) : (
            linkOwners.items.map((it) => (
              <OwnerRow
                key={it.matrikkelenhet || `${it.kommunenummer}-${it.gardsnummer}/${it.bruksnummer}`}
                it={it}
                onHover={onHoverMatrikkel}
              />
            ))
          )}
        </Stack>
      )}
    </>
  );
}

function OwnerRow({ it, onHover }: { it: GeometryOwnerItem; onHover: (g: GeoJSON.Geometry | null) => void }) {
  const matrikkel = it.matrikkelnummertekst || it.matrikkelenhet;
  return (
    <Card
      withBorder
      padding="sm"
      radius="md"
      style={{ cursor: it.geometry ? "pointer" : undefined }}
      onMouseEnter={() => it.geometry && onHover(it.geometry)}
      onMouseLeave={() => onHover(null)}
    >
      <Stack gap={4}>
        <Group gap={6}>
          <Code>{matrikkel}</Code>
          {it.bruksnavn && <Text size="sm" fw={500}>{it.bruksnavn}</Text>}
          {it.kommunenavn && <Badge size="xs" color="gray" variant="light">{it.kommunenavn}</Badge>}
        </Group>
        {it.owners ? (
          <Text size="sm" style={{ whiteSpace: "pre-wrap", fontVariantNumeric: "tabular-nums" }}>
            {it.owners}
          </Text>
        ) : (
          <Text size="xs" c="dimmed">Ingen eierinformasjon tilgjengelig.</Text>
        )}
      </Stack>
    </Card>
  );
}

function MatrikkelDetails({ r }: { r: PointMatrikkelResponse }) {
  const matrikkel = r.matrikkelnummertekst || r.matrikkelenhet;
  const areal = r.lagretberegnetareal != null
    ? `${Math.round(r.lagretberegnetareal).toLocaleString("nb")} m²`
    : null;
  return (
    <Stack gap="sm">
      <Card withBorder padding="sm" radius="md">
        <Stack gap={4}>
          <Group gap={6}>
            <Code>{matrikkel}</Code>
            {r.kommunenavn && (
              <Badge size="xs" color="gray" variant="light">{r.kommunenavn}</Badge>
            )}
          </Group>
          {r.bruksnavn && <Text size="sm" fw={500}>{r.bruksnavn}</Text>}
          <Group gap={12}>
            {r.gardsnummer != null && <Meta label="Gnr" value={r.gardsnummer} />}
            {r.bruksnummer != null && <Meta label="Bnr" value={r.bruksnummer} />}
            {r.festenummer != null && r.festenummer !== 0 && <Meta label="Fnr" value={r.festenummer} />}
            {areal && <Meta label="Areal" value={areal} />}
          </Group>
          {r.arealmerknadtekst && (
            <Text size="xs" c="dimmed">{r.arealmerknadtekst}</Text>
          )}
        </Stack>
      </Card>

      <Card withBorder padding="sm" radius="md">
        <Text size="xs" c="dimmed" tt="uppercase" mb={4}>Eier(e)</Text>
        {r.owner_error ? (
          <Alert icon={<IconAlertTriangle size={14} />} color="orange" variant="light" p="xs">
            <Text size="xs">{r.owner_error}</Text>
          </Alert>
        ) : r.owners ? (
          <Text size="sm" style={{ whiteSpace: "pre-wrap", fontVariantNumeric: "tabular-nums" }}>
            {r.owners}
          </Text>
        ) : (
          <Text size="xs" c="dimmed">Ingen eierinformasjon tilgjengelig.</Text>
        )}
      </Card>

      <Button
        variant="subtle"
        size="xs"
        component="a"
        href={`https://seeiendom.kartverket.no/eiendom/${encodeURIComponent(matrikkel)}`}
        target="_blank"
        rel="noopener"
      >
        Åpne i SeEiendom ↗
      </Button>
    </Stack>
  );
}

function Meta({ label, value }: { label: string; value: number | string }) {
  return (
    <Group gap={2}>
      <Text size="xs" c="dimmed">{label}:</Text>
      <Text size="xs" fw={500}>{value}</Text>
    </Group>
  );
}
