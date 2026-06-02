import { ActionIcon, Alert, Badge, Button, Card, Code, Group, Loader, Stack, Text, Title, Tooltip } from "@mantine/core";
import { IconAlertTriangle, IconHomeDollar, IconInfoCircle, IconMapPin, IconX } from "@tabler/icons-react";
import type { PointMatrikkelResponse } from "./types";

interface Props {
  result: PointMatrikkelResponse | null;
  loading: boolean;
  error: string | null;
  onClear: () => void;
}

/** Grunneier sidebar — Phase 2.
 *
 *  Empty state: prompt the user to click the map. While in this tab every
 *  map click runs api.pointMatrikkelenhet(lat, lon); App stashes the result
 *  in `matrikkelResult` and the response polygon renders on the map via
 *  MapView's matrikkelPolygon layer. We render the metadata + owners here.
 *
 *  Future phases will add: line/polygon selection ("owners for these
 *  links/area"), an Excel export, and matrikkel-number search.
 */
export default function GrunneierPanel({ result, loading, error, onClear }: Props) {
  return (
    <Stack gap="md" p="md">
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Title order={4}>
          <IconHomeDollar size={18} style={{ verticalAlign: "middle", marginRight: 6 }} />
          Grunneier
        </Title>
        {result && (
          <Tooltip label="Tøm valg">
            <ActionIcon size="sm" variant="subtle" color="gray" onClick={onClear}>
              <IconX size={14} />
            </ActionIcon>
          </Tooltip>
        )}
      </Group>

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
    </Stack>
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
