import { useState } from "react";
import { Button, Card, Group, Stack, Text } from "@mantine/core";
import { IconDownload, IconFileTypePdf, IconFileTypeXls, IconChecklist } from "@tabler/icons-react";
import { api } from "./api";
import { notifyError } from "./notify";

interface Props {
  areaCode: string;
  selectedPanels: Set<string>;
  onClearSelection: () => void;
}

/** Sidebar tab that collects all bulk-export actions. Three cards:
 *  Excel manufacturing list (one row per panel), field-installation PDF
 *  (one A4 spread per sign site), and the route-validation XLSX report.
 *  Each download button tracks its own loading state (the backend runs
 *  these on a threadpool so other UI events stay responsive). */
export default function ExportTab({ areaCode, selectedPanels, onClearSelection }: Props) {
  const n = selectedPanels.size;
  // Per-button loading keys — the buttons are mutually independent but each
  // download takes several seconds, so users need explicit per-click
  // feedback ("noen form for tilbakemelding") to know the click registered.
  const [running, setRunning] = useState<Set<string>>(new Set());
  const isRunning = (k: string) => running.has(k);
  const handle = async (key: string, p: Promise<unknown>) => {
    setRunning((s) => new Set(s).add(key));
    try {
      await p;
    } catch (e) {
      notifyError(e);
    } finally {
      setRunning((s) => {
        const next = new Set(s);
        next.delete(key);
        return next;
      });
    }
  };

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
            loading={isRunning("manuf-all")}
            disabled={isRunning("manuf-all")}
            onClick={() => handle("manuf-all", api.downloadManufacturingXlsx(areaCode))}
          >
            Last ned alle
          </Button>
          <Button
            leftSection={<IconDownload size={14} />}
            variant="default"
            size="xs"
            loading={isRunning("manuf-sel")}
            disabled={n === 0 || isRunning("manuf-sel")}
            onClick={() => handle("manuf-sel", api.downloadManufacturingXlsx(areaCode, Array.from(selectedPanels)))}
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
            loading={isRunning("pdf-all")}
            disabled={isRunning("pdf-all")}
            onClick={() => handle("pdf-all", api.downloadFieldPdf(areaCode))}
          >
            Last ned alle
          </Button>
          <Button
            leftSection={<IconDownload size={14} />}
            variant="default"
            size="xs"
            loading={isRunning("pdf-sel")}
            disabled={n === 0 || isRunning("pdf-sel")}
            onClick={() => handle("pdf-sel", api.downloadFieldPdf(areaCode, Array.from(selectedPanels)))}
          >
            Valgte ({n})
          </Button>
        </Group>
      </Card>

      <Card withBorder padding="md" radius="md">
        <Group gap="sm" wrap="nowrap">
          <IconChecklist size={28} stroke={1.5} color="#7a5a18" />
          <Stack gap={2}>
            <Text fw={600}>Rutevalideringsrapport (Excel)</Text>
            <Text size="xs" c="dimmed">Funn per rute + sammendrag. Brukes som tilbakemelding til Kartverket. Kan ta 10–30 sekunder.</Text>
          </Stack>
        </Group>
        <Group mt="md" gap="xs">
          <Button
            leftSection={<IconDownload size={14} />}
            variant="default"
            size="xs"
            loading={isRunning("validation")}
            disabled={isRunning("validation")}
            onClick={() => handle("validation", api.downloadValidationXlsx(areaCode))}
          >
            {isRunning("validation") ? "Bygger rapport…" : "Last ned rapport"}
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
