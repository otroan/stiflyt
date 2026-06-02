import { Alert, Badge, Stack, Text, Title } from "@mantine/core";
import { IconHomeDollar, IconInfoCircle } from "@tabler/icons-react";

/** Placeholder for the in-progress grunneier (landowner) tool merge.
 *
 *  Phase 1 of the merge plan ([[project-grunneier-merge-plan]] in auto-memory)
 *  ships this gated tab to prove the per-user feature-flag wiring end-to-end.
 *  The real owner-by-point + link-selection UIs land in Phase 2/3. Until then
 *  power users can still use the legacy app at `/` (which is also gated by
 *  the same feature flag at the API level — non-grunneier accounts get 403
 *  on /api/v1/owners.xlsx etc.).
 */
export default function GrunneierPanel() {
  return (
    <Stack gap="md" p="md">
      <Title order={4}>
        <IconHomeDollar size={18} style={{ verticalAlign: "middle", marginRight: 6 }} />
        Grunneier
        <Badge size="xs" color="gray" variant="light" ml="xs">kommer snart</Badge>
      </Title>

      <Alert icon={<IconInfoCircle size={16} />} color="blue" variant="light">
        <Text size="sm">
          Grunneier-funksjonaliteten flyttes inn i dette verktøyet i flere trinn.
          Inntil videre kan du bruke den eksisterende grunneier-appen på{" "}
          <Text component="a" href="/" td="underline">/</Text>.
        </Text>
      </Alert>

      <Text size="sm" c="dimmed">
        Planlagt:
      </Text>
      <Stack gap={4} pl="md">
        <Text size="sm">• Klikk på kartet → finn eier av matrikkelenhet</Text>
        <Text size="sm">• Velg flere ruter eller lenker → hent alle eiere</Text>
        <Text size="sm">• Eksport til Excel</Text>
        <Text size="sm">• Søk på matrikkel-nummer og bruksenhet</Text>
      </Stack>
    </Stack>
  );
}
