import { Button, Card, Group, Stack, Text } from "@mantine/core";
import { IconDownload, IconFileTypePdf, IconFileTypeXls } from "@tabler/icons-react";
import { api } from "./api";
import { notifyError } from "./notify";

interface Props {
  areaCode: string;
  selectedPanels: Set<string>;
  onClearSelection: () => void;
}

/** Sidebar tab that collects all bulk-export actions. Two cards:
 *  Excel manufacturing list (one row per panel) and field-installation PDF
 *  (one A4 spread per sign site). Each card supports both "alle" and
 *  "valgte" — the latter respects the panel selection set built up by
 *  ticking checkboxes in the SiteEditor. */
export default function ExportTab({ areaCode, selectedPanels, onClearSelection }: Props) {
  const n = selectedPanels.size;
  const handle = (p: Promise<unknown>) => p.catch((e) => notifyError(e));

  return (
    <Stack gap="md">
      <Card withBorder padding="md" radius="md">
        <Group gap="sm" wrap="nowrap">
          <IconFileTypeXls size={28} stroke={1.5} color="#1f6b3a" />
          <Stack gap={2}>
            <Text fw={600}>Skiltliste (Excel)</Text>
            <Text size="xs" c="dimmed">Én rad per panel. Sendes til skiltprodusent.</Text>
          </Stack>
        </Group>
        <Group mt="md" gap="xs">
          <Button
            leftSection={<IconDownload size={14} />}
            variant="default"
            size="xs"
            onClick={() => handle(api.downloadManufacturingXlsx(areaCode))}
          >
            Last ned alle
          </Button>
          <Button
            leftSection={<IconDownload size={14} />}
            variant="default"
            size="xs"
            disabled={n === 0}
            onClick={() => handle(api.downloadManufacturingXlsx(areaCode, Array.from(selectedPanels)))}
          >
            Valgte ({n})
          </Button>
        </Group>
      </Card>

      <Card withBorder padding="md" radius="md">
        <Group gap="sm" wrap="nowrap">
          <IconFileTypePdf size={28} stroke={1.5} color="#a32d2d" />
          <Stack gap={2}>
            <Text fw={600}>Felt-PDF</Text>
            <Text size="xs" c="dimmed">Ett A4-oppslag per skiltsted med kartutsnitt, paneler og bilder.</Text>
          </Stack>
        </Group>
        <Group mt="md" gap="xs">
          <Button
            leftSection={<IconDownload size={14} />}
            variant="default"
            size="xs"
            onClick={() => handle(api.downloadFieldPdf(areaCode))}
          >
            Last ned alle
          </Button>
          <Button
            leftSection={<IconDownload size={14} />}
            variant="default"
            size="xs"
            disabled={n === 0}
            onClick={() => handle(api.downloadFieldPdf(areaCode, Array.from(selectedPanels)))}
          >
            Valgte ({n})
          </Button>
        </Group>
      </Card>

      {n > 0 && (
        <Card withBorder padding="sm" radius="md" bg="gray.0">
          <Group justify="space-between">
            <Text size="xs" c="dimmed">{n} panel{n === 1 ? "" : "er"} valgt</Text>
            <Button size="xs" variant="subtle" color="gray" onClick={onClearSelection}>
              Tøm utvalget
            </Button>
          </Group>
        </Card>
      )}
    </Stack>
  );
}
