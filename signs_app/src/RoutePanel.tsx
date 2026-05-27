import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Stack,
  Text,
  Tabs,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconArrowBackUp,
  IconCheck,
  IconNotebook,
  IconPencil,
  IconPlus,
  IconReportAnalytics,
  IconTool,
  IconTrash,
  IconUsersGroup,
} from "@tabler/icons-react";
import { api } from "./api";
import { notifyError } from "./notify";
import {
  ROUTE_ANNOTATION_KIND_LABEL_NB,
  type LinkExclusion,
  type RouteAnnotation,
  type RouteAnnotationKind,
  type RouteSummary,
  type RouteValidationResponse,
} from "./types";

interface Props {
  areaCode: string;
  rutenummer: string;
  routeSummary?: RouteSummary;
  onClose: () => void;
  onChanged?: () => void;
  /** Arms the map's place-work-marker mode with a specific work kind. The
   *  next map click drops an annotation of that kind at the clicked point. */
  onArmPlaceWorkMarker?: (kind: RouteAnnotationKind) => void;
  /** True when the place-work-marker mode is currently armed. Used to show
   *  feedback in the UI ("Klikk på kartet for å plassere…"). */
  placeWorkMarkerArmed?: boolean;
  /** Kind currently armed for placement; used to highlight the active button. */
  armedWorkKind?: RouteAnnotationKind | null;
  /** Push loop-arm geometries (coloured) up to the map. Called with [] to clear. */
  onLoopArmsChange?: (arms: { color: string; geometry: GeoJSON.Geometry }[]) => void;
  /** Called after a correction changes the route's shape (exclude/undo) so the
   *  app reloads the route geometry and the map redraws the single path. */
  onRouteShapeChanged?: () => void;
}

type SubTab = "diary" | "inspection" | "dugnad" | "work" | "validation";

// Distinct colours for loop arms — kept clear of the focused-route blue and
// the gold hover line so arm overlays read as their own thing.
const ARM_COLORS = ["#e8590c", "#9c36b5", "#2b8a3e", "#c2255c", "#1098ad"];

const SUBTAB_KINDS: Record<Exclude<SubTab, "validation">, RouteAnnotationKind[]> = {
  diary: ["diary"],
  inspection: ["inspection"],
  dugnad: ["dugnad"],
  work: ["work_klipping", "work_bridge", "work_klopper", "work_other"],
};

const WORK_KIND_OPTIONS: { value: RouteAnnotationKind; label: string }[] = [
  { value: "work_klipping", label: "Klipping" },
  { value: "work_bridge", label: "Bro" },
  { value: "work_klopper", label: "Klopper" },
  { value: "work_other", label: "Annet" },
];

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("nb-NO", {
    year: "numeric", month: "short", day: "numeric",
  });
}

function formatLength(meters: number | undefined | null): string {
  if (meters == null) return "";
  if (meters < 1000) return `${Math.round(meters)} m`;
  const km = meters / 1000;
  return km < 10 ? `${km.toFixed(1)} km` : `${Math.round(km)} km`;
}

export default function RoutePanel({
  areaCode,
  rutenummer,
  routeSummary,
  onClose,
  onChanged,
  onArmPlaceWorkMarker,
  placeWorkMarkerArmed,
  armedWorkKind,
  onLoopArmsChange,
  onRouteShapeChanged,
}: Props) {
  const [tab, setTab] = useState<SubTab>("diary");
  const [annotations, setAnnotations] = useState<RouteAnnotation[]>([]);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);

  const refresh = useMemo(() => async () => {
    setLoading(true);
    try {
      const r = await api.listRouteAnnotations(areaCode, rutenummer);
      setAnnotations(r.annotations);
    } catch (e) {
      notifyError(e);
    } finally {
      setLoading(false);
    }
  }, [areaCode, rutenummer]);

  useEffect(() => { void refresh(); }, [refresh]);

  const lastByKind = useMemo(() => {
    const out: Partial<Record<RouteAnnotationKind, RouteAnnotation>> = {};
    for (const a of annotations) {
      if (!out[a.kind]) out[a.kind] = a;
    }
    return out;
  }, [annotations]);

  const tabKinds = tab === "validation" ? [] : SUBTAB_KINDS[tab];
  const filtered = useMemo(
    () => annotations.filter((a) => tabKinds.includes(a.kind)),
    [annotations, tabKinds],
  );

  const handleDelete = async (id: number) => {
    try {
      await api.deleteRouteAnnotation(id);
      await refresh();
      onChanged?.();
    } catch (e) {
      notifyError(e);
    }
  };

  const handleResolveToggle = async (a: RouteAnnotation) => {
    try {
      await api.updateRouteAnnotation(a.id, {
        resolved_at: a.resolved_at ? null : new Date().toISOString(),
      });
      await refresh();
      onChanged?.();
    } catch (e) {
      notifyError(e);
    }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <div>
          <Title order={4}>{routeSummary?.rutenavn || rutenummer}</Title>
          <Text size="xs" c="dimmed">
            {rutenummer}
            {routeSummary?.length_m != null && ` · ${formatLength(routeSummary.length_m)}`}
          </Text>
          {routeSummary?.disconnected && (
            <Badge size="xs" color="red" variant="light" mt={4}>Usammenhengende rute</Badge>
          )}
        </div>
        <Button variant="subtle" size="xs" onClick={onClose}>Lukk</Button>
      </Group>

      <Group gap="xs" wrap="nowrap">
        <SummaryPill
          label="Siste inspeksjon"
          ann={lastByKind.inspection ?? null}
          color="blue"
        />
        <SummaryPill
          label="Siste dugnad"
          ann={lastByKind.dugnad ?? null}
          color="green"
        />
      </Group>

      <Tabs value={tab} onChange={(v) => v && setTab(v as SubTab)} variant="default" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="diary" leftSection={<IconNotebook size={14} />}>Dagbok</Tabs.Tab>
          <Tabs.Tab value="inspection" leftSection={<IconReportAnalytics size={14} />}>Inspeksjon</Tabs.Tab>
          <Tabs.Tab value="dugnad" leftSection={<IconUsersGroup size={14} />}>Dugnad</Tabs.Tab>
          <Tabs.Tab value="work" leftSection={<IconTool size={14} />}>Arbeid</Tabs.Tab>
          <Tabs.Tab value="validation" leftSection={<IconAlertTriangle size={14} />}>Validering</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value={tab} pt="sm">
          {tab === "validation" ? (
            <ValidationTab
              key={rutenummer}
              areaCode={areaCode}
              rutenummer={rutenummer}
              onLoopArmsChange={onLoopArmsChange}
              onRouteShapeChanged={() => { onRouteShapeChanged?.(); onChanged?.(); }}
            />
          ) : (
          <Stack gap="xs">
            {tab !== "work" && !adding && (
              <Button
                size="xs"
                variant="light"
                leftSection={<IconPlus size={14} />}
                onClick={() => setAdding(true)}
              >
                {tab === "diary" && "Ny dagboknotis"}
                {tab === "inspection" && "Ny inspeksjon"}
                {tab === "dugnad" && "Ny dugnadsrapport"}
              </Button>
            )}
            {tab !== "work" && adding && (
              <NewAnnotationForm
                tab={tab}
                areaCode={areaCode}
                rutenummer={rutenummer}
                onCancel={() => setAdding(false)}
                onSaved={async () => {
                  setAdding(false);
                  await refresh();
                  onChanged?.();
                }}
              />
            )}
            {tab === "work" && (
              <WorkPlacementBar
                armed={!!placeWorkMarkerArmed}
                armedKind={armedWorkKind ?? null}
                onArm={(k) => onArmPlaceWorkMarker?.(k)}
              />
            )}
            {loading && <Text size="xs" c="dimmed">Laster…</Text>}
            {!loading && filtered.length === 0 && !adding && (
              <Text size="xs" c="dimmed">Ingen oppføringer ennå.</Text>
            )}
            {filtered.map((a) => (
              <AnnotationCard
                key={a.id}
                ann={a}
                showResolve={tab === "work"}
                onDelete={() => handleDelete(a.id)}
                onResolveToggle={() => handleResolveToggle(a)}
                onSaved={async () => { await refresh(); onChanged?.(); }}
              />
            ))}
          </Stack>
          )}
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

function SummaryPill({ label, ann, color }: { label: string; ann: RouteAnnotation | null; color: string }) {
  return (
    <Card withBorder padding="xs" radius="md" style={{ flex: 1, minWidth: 0 }}>
      <Text size="10px" c="dimmed" tt="uppercase">{label}</Text>
      {ann ? (
        <>
          <Text size="sm" lineClamp={1} fw={500}>{ann.title || "(uten tittel)"}</Text>
          <Group gap={6}>
            <Badge size="xs" color={color} variant="light">{formatDate(ann.occurred_at)}</Badge>
            {ann.recorded_by && <Text size="10px" c="dimmed" truncate>{ann.recorded_by}</Text>}
          </Group>
        </>
      ) : (
        <Text size="xs" c="dimmed">Aldri</Text>
      )}
    </Card>
  );
}

function AnnotationCard({ ann, showResolve, onDelete, onResolveToggle, onSaved }: {
  ann: RouteAnnotation;
  showResolve: boolean;
  onDelete: () => void;
  onResolveToggle: () => void;
  onSaved: () => void;
}) {
  const resolved = !!ann.resolved_at;
  const [editing, setEditing] = useState(false);
  if (editing) {
    return (
      <EditAnnotationForm
        ann={ann}
        showKindPicker={showResolve}
        onCancel={() => setEditing(false)}
        onSaved={() => { setEditing(false); onSaved(); }}
      />
    );
  }
  return (
    <Card
      withBorder
      padding="xs"
      radius="sm"
      bg={resolved ? "gray.0" : undefined}
    >
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <div style={{ flex: 1, minWidth: 0 }}>
          <Group gap={6} wrap="nowrap">
            {showResolve && (
              <Badge size="xs" color={resolved ? "gray" : "orange"} variant="light">
                {ROUTE_ANNOTATION_KIND_LABEL_NB[ann.kind]}
              </Badge>
            )}
            <Text fw={500} size="sm" lineClamp={1}>{ann.title || "(uten tittel)"}</Text>
          </Group>
          {ann.body && (
            <Text size="xs" c="dimmed" mt={2} style={{ whiteSpace: "pre-wrap" }}>
              {ann.body}
            </Text>
          )}
          <Group gap={6} mt={4}>
            <Text size="10px" c="dimmed">{formatDate(ann.occurred_at)}</Text>
            {ann.recorded_by && <Text size="10px" c="dimmed">· {ann.recorded_by}</Text>}
            {ann.lon != null && ann.lat != null && (
              <Text size="10px" c="dimmed">· {ann.lat.toFixed(4)}, {ann.lon.toFixed(4)}</Text>
            )}
          </Group>
        </div>
        <Group gap={2} wrap="nowrap">
          <Tooltip label="Rediger">
            <ActionIcon size="sm" variant="subtle" color="gray" onClick={() => setEditing(true)}>
              <IconPencil size={14} />
            </ActionIcon>
          </Tooltip>
          {showResolve && (
            <Tooltip label={resolved ? "Marker som uløst" : "Marker som løst"}>
              <ActionIcon
                size="sm"
                variant="subtle"
                color={resolved ? "gray" : "green"}
                onClick={onResolveToggle}
              >
                <IconCheck size={14} />
              </ActionIcon>
            </Tooltip>
          )}
          <Tooltip label="Slett">
            <ActionIcon size="sm" variant="subtle" color="red" onClick={onDelete}>
              <IconTrash size={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>
    </Card>
  );
}

function EditAnnotationForm({ ann, showKindPicker, onCancel, onSaved }: {
  ann: RouteAnnotation;
  showKindPicker: boolean;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState(ann.title ?? "");
  const [body, setBody] = useState(ann.body ?? "");
  const [kind, setKind] = useState<RouteAnnotationKind>(ann.kind);
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    setSaving(true);
    try {
      await api.updateRouteAnnotation(ann.id, {
        title: title.trim() || null,
        body: body.trim() || null,
        ...(showKindPicker && kind !== ann.kind ? { kind } : {}),
      });
      onSaved();
    } catch (e) {
      notifyError(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card withBorder padding="xs" radius="sm">
      <Stack gap={6}>
        {showKindPicker && (
          <Group gap={6} wrap="wrap">
            {WORK_KIND_OPTIONS.map((opt) => (
              <Button
                key={opt.value}
                size="compact-xs"
                variant={kind === opt.value ? "filled" : "default"}
                onClick={() => setKind(opt.value)}
              >
                {opt.label}
              </Button>
            ))}
          </Group>
        )}
        <TextInput
          size="xs"
          placeholder="Kort tittel"
          value={title}
          onChange={(e) => setTitle(e.currentTarget.value)}
        />
        <Textarea
          size="xs"
          placeholder="Beskrivelse"
          value={body}
          onChange={(e) => setBody(e.currentTarget.value)}
          minRows={3}
          autosize
        />
        <Group justify="flex-end" gap="xs">
          <Button size="xs" variant="subtle" onClick={onCancel} disabled={saving}>
            Avbryt
          </Button>
          <Button size="xs" onClick={submit} loading={saving}>
            Lagre
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}

function NewAnnotationForm({ tab, areaCode, rutenummer, onCancel, onSaved }: {
  tab: Exclude<SubTab, "work">;
  areaCode: string;
  rutenummer: string;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    setSaving(true);
    try {
      await api.createRouteAnnotation(areaCode, rutenummer, {
        kind: tab,
        title: title.trim() || null,
        body: body.trim() || null,
      });
      onSaved();
    } catch (e) {
      notifyError(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card withBorder padding="xs" radius="sm">
      <Stack gap={6}>
        <TextInput
          size="xs"
          placeholder="Kort tittel"
          value={title}
          onChange={(e) => setTitle(e.currentTarget.value)}
        />
        <Textarea
          size="xs"
          placeholder={tab === "diary" ? "Notater" : "Beskrivelse"}
          value={body}
          onChange={(e) => setBody(e.currentTarget.value)}
          minRows={3}
          autosize
        />
        <Group justify="flex-end" gap="xs">
          <Button size="xs" variant="subtle" onClick={onCancel} disabled={saving}>
            Avbryt
          </Button>
          <Button size="xs" onClick={submit} loading={saving}>
            Lagre
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}

function WorkPlacementBar({ armed, armedKind, onArm }: {
  armed: boolean;
  armedKind: RouteAnnotationKind | null;
  onArm: (kind: RouteAnnotationKind) => void;
}) {
  return (
    <Card withBorder padding="xs" radius="sm">
      <Stack gap={6}>
        <Text size="xs" c="dimmed">
          Velg type og klikk deretter et punkt på kartet for å markere arbeidsbehovet.
        </Text>
        <Group gap={6} wrap="wrap">
          {WORK_KIND_OPTIONS.map((opt) => {
            const isArmed = armed && armedKind === opt.value;
            return (
              <Button
                key={opt.value}
                size="compact-xs"
                variant={isArmed ? "filled" : "default"}
                color={isArmed ? "orange" : undefined}
                onClick={() => onArm(opt.value)}
              >
                {opt.label}
              </Button>
            );
          })}
        </Group>
        {armed && armedKind && (
          <Text size="xs" c="orange.7">
            Armert ({WORK_KIND_OPTIONS.find((o) => o.value === armedKind)?.label ?? armedKind}) — klikk på kartet.
          </Text>
        )}
      </Stack>
    </Card>
  );
}

function ValidationTab({ areaCode, rutenummer, onLoopArmsChange, onRouteShapeChanged }: {
  areaCode: string;
  rutenummer: string;
  onLoopArmsChange?: (arms: { color: string; geometry: GeoJSON.Geometry }[]) => void;
  onRouteShapeChanged: () => void;
}) {
  const [val, setVal] = useState<RouteValidationResponse | null>(null);
  const [exclusions, setExclusions] = useState<LinkExclusion[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [v, ex] = await Promise.all([
        api.getRouteValidation(areaCode, rutenummer),
        api.listLinkExclusions(areaCode, rutenummer),
      ]);
      setVal(v);
      setExclusions(ex.exclusions);
    } catch (e) {
      notifyError(e);
    } finally {
      setLoading(false);
    }
  }, [areaCode, rutenummer]);

  useEffect(() => { void refresh(); }, [refresh]);

  const loopIssue = val?.errors.find((e) => e.type === "ROUTE_HAS_LOOP");

  const armEntries = useMemo(() => {
    const groups = loopIssue?.arm_groups ?? [];
    const out: { key: string; color: string; links: number[]; length_m: number; geometry?: GeoJSON.Geometry | null }[] = [];
    let ci = 0;
    groups.forEach((g, gi) => {
      g.arms.forEach((a, ai) => {
        out.push({
          key: `${gi}-${ai}`,
          color: ARM_COLORS[ci % ARM_COLORS.length],
          links: a.links,
          length_m: a.length_m,
          geometry: a.geometry,
        });
        ci++;
      });
    });
    return out;
  }, [loopIssue]);

  // Mirror the arms onto the map; clear when leaving the tab / unmounting.
  useEffect(() => {
    onLoopArmsChange?.(
      armEntries
        .filter((a) => a.geometry)
        .map((a) => ({ color: a.color, geometry: a.geometry as GeoJSON.Geometry })),
    );
    return () => onLoopArmsChange?.([]);
  }, [armEntries, onLoopArmsChange]);

  const removeArm = async (links: number[]) => {
    setBusy(true);
    try {
      await api.addLinkExclusions(areaCode, rutenummer, { link_ids: links, reason: "wrong_arm" });
      onRouteShapeChanged();
      await refresh();
    } catch (e) {
      notifyError(e);
    } finally {
      setBusy(false);
    }
  };

  const undoAll = async () => {
    setBusy(true);
    try {
      await api.clearLinkExclusions(areaCode, rutenummer);
      onRouteShapeChanged();
      await refresh();
    } catch (e) {
      notifyError(e);
    } finally {
      setBusy(false);
    }
  };

  const otherIssues = useMemo(() => {
    if (!val) return [];
    return [...val.errors, ...val.warnings, ...val.info].filter((i) => i.type !== "ROUTE_HAS_LOOP");
  }, [val]);

  if (loading && !val) return <Text size="xs" c="dimmed">Laster validering…</Text>;
  if (!val) return null;

  const statusColor = val.status === "OK" ? "green" : val.status === "WARNING" ? "yellow" : "red";

  return (
    <Stack gap="sm">
      <Group gap="xs">
        <Badge color={statusColor} variant="light">{val.status}</Badge>
        <Text size="xs" c="dimmed">
          {val.errors.length} feil · {val.warnings.length} advarsler
        </Text>
      </Group>

      {loopIssue && (
        <Card withBorder padding="sm" radius="md">
          <Group gap={6} mb={6}>
            <IconAlertTriangle size={16} color="#e8590c" />
            <Text fw={600} size="sm">Sløyfe oppdaget</Text>
          </Group>
          <Text size="xs" c="dimmed" mb="xs">{loopIssue.message}</Text>
          {loopIssue.decomposable === false && (
            <Text size="xs" c="orange.7" mb="xs">
              Sløyfen kan ikke deles automatisk i armer — må vurderes manuelt.
            </Text>
          )}
          <Stack gap={6}>
            {armEntries.map((a, i) => (
              <Group key={a.key} justify="space-between" wrap="nowrap">
                <Group gap={8} wrap="nowrap">
                  <span style={{ width: 14, height: 14, borderRadius: 3, background: a.color, flexShrink: 0 }} />
                  <Text size="sm">
                    Arm {i + 1} · {formatLength(a.length_m)} · {a.links.length} lenker
                  </Text>
                </Group>
                <Button size="compact-xs" color="red" variant="light" loading={busy} onClick={() => removeArm(a.links)}>
                  Fjern denne
                </Button>
              </Group>
            ))}
          </Stack>
        </Card>
      )}

      {exclusions.length > 0 && (
        <Card withBorder padding="sm" radius="md" bg="gray.0">
          <Group justify="space-between" mb={6}>
            <Text fw={600} size="sm">Ekskluderte lenker ({exclusions.length})</Text>
            <Button size="compact-xs" variant="subtle" leftSection={<IconArrowBackUp size={14} />} loading={busy} onClick={undoAll}>
              Angre alle
            </Button>
          </Group>
          <Text size="xs" c="dimmed">{exclusions.map((e) => e.link_id).join(", ")}</Text>
        </Card>
      )}

      {otherIssues.length > 0 && (
        <Stack gap={4}>
          {otherIssues.map((i, idx) => (
            <Group key={idx} gap={6} wrap="nowrap" align="flex-start">
              <Badge size="xs" variant="light" color={i.severity === "error" ? "red" : i.severity === "warning" ? "yellow" : "blue"}>
                {i.severity}
              </Badge>
              <Text size="xs" c="dimmed">{i.message}</Text>
            </Group>
          ))}
        </Stack>
      )}

      {val.status === "OK" && exclusions.length === 0 && (
        <Text size="xs" c="dimmed">Ingen feil funnet.</Text>
      )}
    </Stack>
  );
}
