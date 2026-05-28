import { ActionIcon, Button, Card, FileButton, Group, Stack, Text, Tooltip } from "@mantine/core";
import { IconTrash, IconUpload } from "@tabler/icons-react";
import type { GpxTrack } from "./types";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("nb-NO", { year: "numeric", month: "short", day: "numeric" });
}

export default function GpxPanel({ areaCode, tracks, onUpload, onDelete }: {
  areaCode: string;
  tracks: GpxTrack[];
  onUpload: (files: File[]) => void;
  onDelete: (id: number) => void;
}) {
  return (
    <Stack gap="sm" p="sm">
      <FileButton
        onChange={(files) => { if (files && files.length) onUpload(files); }}
        accept=".gpx,application/gpx+xml,application/xml"
        multiple
      >
        {(props) => (
          <Button {...props} size="xs" variant="light" leftSection={<IconUpload size={14} />}>
            Last opp GPX
          </Button>
        )}
      </FileButton>
      <Text size="xs" c="dimmed">
        Faktisk gåtte spor for «{areaCode}». Vises som grønt lag på kartet (slå av/på i kartpanelet).
        Flere filer kan velges samtidig.
      </Text>

      {tracks.length === 0 && (
        <Text size="xs" c="dimmed">Ingen spor lastet opp ennå.</Text>
      )}

      {tracks.map((t) => (
        <Card key={t.id} withBorder padding="xs" radius="sm">
          <Group justify="space-between" wrap="nowrap" align="flex-start">
            <div style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm" fw={500} lineClamp={1}>{t.name || `spor ${t.id}`}</Text>
              <Text size="xs" c="dimmed">
                {t.length_km != null ? `${t.length_km} km` : ""}
                {t.point_count != null ? ` · ${t.point_count} pkt` : ""}
                {t.uploaded_at ? ` · ${formatDate(t.uploaded_at)}` : ""}
                {t.uploaded_by ? ` · ${t.uploaded_by}` : ""}
              </Text>
            </div>
            <Tooltip label="Slett spor">
              <ActionIcon size="sm" variant="subtle" color="red" onClick={() => onDelete(t.id)}>
                <IconTrash size={14} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Card>
      ))}
    </Stack>
  );
}
