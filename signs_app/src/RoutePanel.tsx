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
  IconArrowsLeftRight,
  IconCheck,
  IconMountain,
  IconNotebook,
  IconPencil,
  IconPhoto,
  IconPlus,
  IconReportAnalytics,
  IconTool,
  IconTrash,
  IconUsersGroup,
} from "@tabler/icons-react";
import { api } from "./api";
import { naismithLabel } from "./naismith";
import { notifyError } from "./notify";
import {
  ROUTE_ANNOTATION_KIND_LABEL_NB,
  type ElevationProfile,
  type FieldPhoto,
  type GpxComparison,
  type LinkBridge,
  type LinkExclusion,
  type MetadataOverride,
  type RouteAnnotation,
  type RouteAnnotationKind,
  type RouteSummary,
  type RouteValidationResponse,
} from "./types";

// Metadata issues resolved by setting a canonical route value (vs. those that
// need a Kartverket row deletion, which the override can't fix).
const METADATA_FIXABLE = new Set([
  "INCONSISTENT_RUTENAVN", "INCONSISTENT_VEDLIKEHOLDSANSVARLIG",
  "INCONSISTENT_RUTETYPE", "INCONSISTENT_GRADERING",
  "RUTENAVN_UKJENT", "MISSING_RUTENAVN", "MISSING_RUTENAVN_SOME_SEGMENTS",
  "MISSING_VEDLIKEHOLDSANSVARLIG", "MISSING_VEDLIKEHOLDSANSVARLIG_SOME_SEGMENTS",
  "RUTENAVN_SUGGESTION",
]);

const METADATA_FIELDS: { key: "rutenavn" | "vedlikeholdsansvarlig" | "rutetype" | "gradering"; label: string }[] = [
  { key: "rutenavn", label: "Rutenavn" },
  { key: "vedlikeholdsansvarlig", label: "Vedlikeholdsansvarlig" },
  { key: "rutetype", label: "Rutetype" },
  { key: "gradering", label: "Gradering" },
];

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
  /** When set, open the panel directly on this sub-tab (e.g. navigating from
   *  the Kvalitet list opens "validation"). */
  initialSubTab?: "validation" | null;
  /** Called once initialSubTab has been applied, so the parent can clear it. */
  onInitialSubTabConsumed?: () => void;
  /** Open the shared photo lightbox (App owns it). */
  onOpenPhotos?: (photos: FieldPhoto[], index: number) => void;
  /** Bumped by App after an external write (e.g. dropping a work marker via the
   *  map) so the panel re-fetches its annotations list. */
  refreshKey?: number;
  /** Called with an annotation id while the user hovers a card in the list, and
   *  null on mouse-leave. App forwards this to MapView so the matching work
   *  marker is highlighted (and panned to if offscreen). */
  onHoverAnnotation?: (id: number | null) => void;
}

type SubTab = "diary" | "inspection" | "dugnad" | "work" | "validation" | "bilder" | "hoyde";

// Distinct colours for loop arms — kept clear of the focused-route blue and
// the gold hover line so arm overlays read as their own thing.
const ARM_COLORS = ["#e8590c", "#9c36b5", "#2b8a3e", "#c2255c", "#1098ad"];

const SUBTAB_KINDS: Record<Exclude<SubTab, "validation" | "bilder" | "hoyde">, RouteAnnotationKind[]> = {
  diary: ["diary"],
  inspection: ["inspection"],
  dugnad: ["dugnad"],
  work: ["work_klipping", "work_bridge", "work_klopper", "work_skilt", "work_other"],
};

const WORK_KIND_OPTIONS: { value: RouteAnnotationKind; label: string }[] = [
  { value: "work_klipping", label: "Klipping" },
  { value: "work_bridge", label: "Bro" },
  { value: "work_klopper", label: "Klopper" },
  { value: "work_skilt", label: "Skilt" },
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
  initialSubTab,
  onInitialSubTabConsumed,
  onOpenPhotos,
  refreshKey,
  onHoverAnnotation,
}: Props) {
  const [tab, setTab] = useState<SubTab>(initialSubTab ?? "diary");

  useEffect(() => {
    if (initialSubTab) {
      setTab(initialSubTab);
      onInitialSubTabConsumed?.();
    }
  }, [initialSubTab, onInitialSubTabConsumed]);
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

  useEffect(() => { void refresh(); }, [refresh, refreshKey]);

  const lastByKind = useMemo(() => {
    const out: Partial<Record<RouteAnnotationKind, RouteAnnotation>> = {};
    for (const a of annotations) {
      if (!out[a.kind]) out[a.kind] = a;
    }
    return out;
  }, [annotations]);

  const tabKinds = tab === "validation" || tab === "bilder" || tab === "hoyde" ? [] : SUBTAB_KINDS[tab];
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
            {naismithLabel(routeSummary?.length_m, routeSummary?.ascent_m)
              && ` · ⏱ ~${naismithLabel(routeSummary?.length_m, routeSummary?.ascent_m)}`}
          </Text>
          {routeSummary?.disconnected && (
            <Badge size="xs" color="red" variant="light" mt={4}>Usammenhengende rute</Badge>
          )}
        </div>
        <Group gap={4} wrap="nowrap">
          <Button
            component="a"
            href={`/api/v1/routes/${areaCode}/${encodeURIComponent(rutenummer)}/kort`}
            target="_blank"
            rel="noopener"
            variant="subtle"
            size="xs"
          >
            Rutekort
          </Button>
          <Button variant="subtle" size="xs" onClick={onClose}>Lukk</Button>
        </Group>
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
          <Tabs.Tab value="bilder" leftSection={<IconPhoto size={14} />}>Bilder</Tabs.Tab>
          <Tabs.Tab value="hoyde" leftSection={<IconMountain size={14} />}>Høyde</Tabs.Tab>
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
          ) : tab === "bilder" ? (
            <PhotosTab key={rutenummer} areaCode={areaCode} rutenummer={rutenummer} onOpenPhotos={onOpenPhotos} />
          ) : tab === "hoyde" ? (
            <ElevationTab key={rutenummer} areaCode={areaCode} rutenummer={rutenummer} />
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
                onHover={onHoverAnnotation}
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

function AnnotationCard({ ann, showResolve, onDelete, onResolveToggle, onSaved, onHover }: {
  ann: RouteAnnotation;
  showResolve: boolean;
  onDelete: () => void;
  onResolveToggle: () => void;
  onSaved: () => void;
  onHover?: (id: number | null) => void;
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
  const hoverable = onHover && ann.lon != null && ann.lat != null;
  return (
    <Card
      withBorder
      padding="xs"
      radius="sm"
      bg={resolved ? "gray.0" : undefined}
      onMouseEnter={hoverable ? () => onHover!(ann.id) : undefined}
      onMouseLeave={hoverable ? () => onHover!(null) : undefined}
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
  const [bridges, setBridges] = useState<LinkBridge[]>([]);
  const [override, setOverride] = useState<MetadataOverride | null>(null);
  const [gpxCmp, setGpxCmp] = useState<GpxComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [v, ex, br, mo, gc] = await Promise.all([
        api.getRouteValidation(areaCode, rutenummer),
        api.listLinkExclusions(areaCode, rutenummer),
        api.listLinkBridges(areaCode, rutenummer),
        api.getMetadataOverride(areaCode, rutenummer),
        api.getGpxComparison(areaCode, rutenummer),
      ]);
      setVal(v);
      setExclusions(ex.exclusions);
      setBridges(br.bridges);
      setOverride(mo.override);
      setGpxCmp(gc);
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

  const disconnectedIssue = val?.errors.find((e) => e.type === "ROUTE_DISCONNECTED");

  const addBridge = async (a_node: number, b_node: number) => {
    setBusy(true);
    try {
      await api.addLinkBridge(areaCode, rutenummer, { a_node, b_node, reason: "digitizing_gap" });
      onRouteShapeChanged();
      await refresh();
    } catch (e) {
      notifyError(e);
    } finally {
      setBusy(false);
    }
  };

  const removeBridge = async (a_node: number, b_node: number) => {
    setBusy(true);
    try {
      await api.clearLinkBridges(areaCode, rutenummer, [a_node, b_node]);
      onRouteShapeChanged();
      await refresh();
    } catch (e) {
      notifyError(e);
    } finally {
      setBusy(false);
    }
  };

  // Suggested rutenavn (from RUTENAVN_SUGGESTION) + distinct values seen per
  // field (from INCONSISTENT_*), to prefill / offer in the metadata form.
  const metadataHints = useMemo(() => {
    const suggestions: Record<string, string[]> = {};
    let suggestedRutenavn: string | null = null;
    if (val) {
      for (const i of [...val.errors, ...val.warnings, ...val.info]) {
        if (i.type === "RUTENAVN_SUGGESTION" && typeof i.suggested_rutenavn === "string") {
          suggestedRutenavn = i.suggested_rutenavn;
        }
        const m: Record<string, string> = {
          INCONSISTENT_RUTENAVN: "rutenavn",
          INCONSISTENT_VEDLIKEHOLDSANSVARLIG: "vedlikeholdsansvarlig",
          INCONSISTENT_RUTETYPE: "rutetype",
          INCONSISTENT_GRADERING: "gradering",
        };
        const field = m[i.type];
        if (field && Array.isArray(i.values)) {
          suggestions[field] = (i.values as unknown[]).map(String);
        }
      }
    }
    return { suggestions, suggestedRutenavn };
  }, [val]);

  const hasMetadataIssue = useMemo(
    () => !!val && [...val.errors, ...val.warnings, ...val.info].some((i) => METADATA_FIXABLE.has(i.type)),
    [val],
  );

  const otherIssues = useMemo(() => {
    if (!val) return [];
    return [...val.errors, ...val.warnings, ...val.info].filter(
      (i) => i.type !== "ROUTE_HAS_LOOP" && i.type !== "ROUTE_DISCONNECTED" && !METADATA_FIXABLE.has(i.type),
    );
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

      {disconnectedIssue && (
        <Card withBorder padding="sm" radius="md">
          <Group gap={6} mb={6}>
            <IconAlertTriangle size={16} color="#e8590c" />
            <Text fw={600} size="sm">Usammenhengende rute ({disconnectedIssue.component_count} deler)</Text>
          </Group>
          <Text size="xs" c="dimmed" mb="xs">{disconnectedIssue.message}</Text>
          <Stack gap={6}>
            {(disconnectedIssue.bridge_suggestions ?? []).map((s) => (
              <Group key={`${s.a_node}-${s.b_node}`} justify="space-between" wrap="nowrap">
                <Text size="sm">Brudd: {formatLength(s.gap_m)}</Text>
                <Button size="compact-xs" variant="light" loading={busy} onClick={() => addBridge(s.a_node, s.b_node)}>
                  Koble sammen
                </Button>
              </Group>
            ))}
          </Stack>
        </Card>
      )}

      {bridges.length > 0 && (
        <Card withBorder padding="sm" radius="md" bg="gray.0">
          <Text fw={600} size="sm" mb={6}>Broer ({bridges.length})</Text>
          <Stack gap={4}>
            {bridges.map((b) => (
              <Group key={`${b.a_node}-${b.b_node}`} justify="space-between" wrap="nowrap">
                <Text size="xs" c="dimmed">{b.a_node} ↔ {b.b_node}{b.comment ? ` · ${b.comment}` : ""}</Text>
                <Button size="compact-xs" variant="subtle" leftSection={<IconArrowBackUp size={14} />} loading={busy} onClick={() => removeBridge(b.a_node, b.b_node)}>
                  Angre
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

      {(hasMetadataIssue || override) && (
        <MetadataFixCard
          areaCode={areaCode}
          rutenummer={rutenummer}
          override={override}
          suggestions={metadataHints.suggestions}
          suggestedRutenavn={metadataHints.suggestedRutenavn}
          onSaved={async () => { await refresh(); onRouteShapeChanged(); }}
        />
      )}

      {gpxCmp && gpxCmp.tracks.length > 0 && (
        <Card withBorder padding="sm" radius="md">
          <Text fw={600} size="sm" mb={6}>GPS-fasit</Text>
          {gpxCmp.measured_factor != null ? (
            <Text size="xs" mb="xs">
              Målt avstandsfaktor <b>{gpxCmp.measured_factor}×</b> mot antatt {gpxCmp.assumed_factor}× — fra {gpxCmp.n_tracks_used} spor som dekker ruta.
            </Text>
          ) : (
            <Text size="xs" c="dimmed" mb="xs">For lav dekning fra sporene til å måle en faktor.</Text>
          )}
          <Stack gap={4}>
            {gpxCmp.tracks.map((t) => (
              <Group key={t.track_id} justify="space-between" wrap="nowrap">
                <Text size="xs" lineClamp={1} style={{ flex: 1 }}>{t.name || `spor ${t.track_id}`}</Text>
                <Text size="xs" c="dimmed">
                  dekker {t.coverage_pct ?? "–"}% · {t.factor != null ? `${t.factor}×` : "–"}
                </Text>
              </Group>
            ))}
          </Stack>
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

      {val.status === "OK" && exclusions.length === 0 && bridges.length === 0 && !override && (
        <Text size="xs" c="dimmed">Ingen feil funnet.</Text>
      )}
    </Stack>
  );
}

function MetadataFixCard({ areaCode, rutenummer, override, suggestions, suggestedRutenavn, onSaved }: {
  areaCode: string;
  rutenummer: string;
  override: MetadataOverride | null;
  suggestions: Record<string, string[]>;
  suggestedRutenavn: string | null;
  onSaved: () => void;
}) {
  const initial = useMemo(() => ({
    rutenavn: override?.rutenavn ?? "",
    vedlikeholdsansvarlig: override?.vedlikeholdsansvarlig ?? "",
    rutetype: override?.rutetype ?? "",
    gradering: override?.gradering ?? "",
  }), [override]);
  const [vals, setVals] = useState(initial);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setVals(initial); }, [initial]);

  const set = (k: keyof typeof vals, v: string) => setVals((p) => ({ ...p, [k]: v }));

  const save = async () => {
    setBusy(true);
    try {
      await api.putMetadataOverride(areaCode, rutenummer, vals);
      onSaved();
    } catch (e) { notifyError(e); } finally { setBusy(false); }
  };

  const reset = async () => {
    setBusy(true);
    try {
      await api.clearMetadataOverride(areaCode, rutenummer);
      onSaved();
    } catch (e) { notifyError(e); } finally { setBusy(false); }
  };

  return (
    <Card withBorder padding="sm" radius="md">
      <Group justify="space-between" mb={6}>
        <Text fw={600} size="sm">Metadata</Text>
        {override && <Badge size="xs" color="blue" variant="light">overstyrt</Badge>}
      </Group>
      <Stack gap={8}>
        {METADATA_FIELDS.map(({ key, label }) => {
          const chips = key === "rutenavn"
            ? [...(suggestedRutenavn ? [suggestedRutenavn] : []), ...(suggestions.rutenavn ?? [])]
            : (suggestions[key] ?? []);
          const uniqueChips = Array.from(new Set(chips)).filter((c) => c && c.toLowerCase() !== "ukjent");
          return (
            <div key={key}>
              <TextInput
                size="xs"
                label={label}
                value={vals[key]}
                placeholder="(behold Kartverket-verdi)"
                onChange={(e) => set(key, e.currentTarget.value)}
              />
              {uniqueChips.length > 0 && (
                <Group gap={4} mt={2}>
                  {uniqueChips.map((c) => (
                    <Badge key={c} size="xs" variant="light" style={{ cursor: "pointer" }} onClick={() => set(key, c)}>
                      {c}
                    </Badge>
                  ))}
                </Group>
              )}
            </div>
          );
        })}
        <Group justify="flex-end" gap="xs">
          {override && (
            <Button size="xs" variant="subtle" color="gray" loading={busy} onClick={reset}>
              Tilbakestill
            </Button>
          )}
          <Button size="xs" loading={busy} onClick={save}>Lagre</Button>
        </Group>
      </Stack>
    </Card>
  );
}

function PhotosTab({ areaCode, rutenummer, onOpenPhotos }: {
  areaCode: string;
  rutenummer: string;
  onOpenPhotos?: (photos: FieldPhoto[], index: number) => void;
}) {
  const [photos, setPhotos] = useState<FieldPhoto[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.getRoutePhotos(areaCode, rutenummer)
      .then((r) => { if (!cancelled) setPhotos(r.photos); })
      .catch((e) => { if (!cancelled) notifyError(e); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [areaCode, rutenummer]);

  if (loading) return <Text size="xs" c="dimmed">Laster bilder…</Text>;
  if (photos.length === 0) {
    return <Text size="xs" c="dimmed">Ingen bilder i nærheten av ruta. Plasser bilder på kartet i Bilder-fanen.</Text>;
  }

  return (
    <Stack gap={6}>
      <Text size="xs" c="dimmed">{photos.length} bilde{photos.length === 1 ? "" : "r"} nær ruta</Text>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4 }}>
        {photos.map((p, i) => (
          <img
            key={p.id}
            src={p.thumb_url}
            alt={p.caption ?? ""}
            title={p.caption ?? ""}
            loading="lazy"
            style={{ width: "100%", aspectRatio: "1 / 1", objectFit: "cover", borderRadius: 4, cursor: "pointer", display: "block" }}
            onClick={() => onOpenPhotos?.(photos, i)}
          />
        ))}
      </div>
    </Stack>
  );
}

function fmtKm(m: number | null | undefined): string {
  if (m == null) return "–";
  const km = m / 1000;
  return km < 10 ? `${km.toFixed(1)} km` : `${Math.round(km)} km`;
}

function ElevationTab({ areaCode, rutenummer }: { areaCode: string; rutenummer: string }) {
  const [prof, setProf] = useState<ElevationProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [reversed, setReversed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setReversed(false);
    api.getRouteElevation(areaCode, rutenummer)
      .then((p) => { if (!cancelled) setProf(p); })
      .catch((e) => { if (!cancelled) notifyError(e); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [areaCode, rutenummer]);

  if (loading && !prof) return <Text size="xs" c="dimmed">Henter høydeprofil fra Kartverket…</Text>;
  if (!prof) return <Text size="xs" c="dimmed">Ingen høydedata.</Text>;

  const leftName = reversed ? prof.end_name : prof.start_name;
  const rightName = reversed ? prof.start_name : prof.end_name;

  return (
    <Stack gap="sm">
      <Group gap="md">
        <Stat label="Lengde (3D)" value={fmtKm(prof.length_3d_m)} />
        <Stat label="Stigning" value={prof.ascent_m != null ? `${Math.round(prof.ascent_m)} m` : "–"} />
        <Stat label="Høyde" value={prof.min_z != null && prof.max_z != null ? `${Math.round(prof.min_z)}–${Math.round(prof.max_z)} m` : "–"} />
        <Stat label="Tid (Naismith)" value={naismithLabel(prof.length_2d_m, prof.ascent_m) ?? "–"} />
      </Group>
      <ElevationChart samples={prof.samples} reversed={reversed} />
      <Group justify="space-between" wrap="nowrap" gap={6}>
        <Text size="xs" fw={500} style={{ flex: 1, minWidth: 0 }} lineClamp={1}>
          {leftName || "–"}
        </Text>
        <Button
          size="compact-xs"
          variant="subtle"
          leftSection={<IconArrowsLeftRight size={12} />}
          onClick={() => setReversed((v) => !v)}
        >
          Snu
        </Button>
        <Text size="xs" fw={500} ta="right" style={{ flex: 1, minWidth: 0 }} lineClamp={1}>
          {rightName || "–"}
        </Text>
      </Group>
      <Text size="10px" c="dimmed">
        2D {fmtKm(prof.length_2d_m)} · fall {prof.descent_m != null ? `${Math.round(prof.descent_m)} m` : "–"}
        {prof.datakilde ? ` · kilde ${prof.datakilde}` : ""}
      </Text>
    </Stack>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Text size="10px" c="dimmed" tt="uppercase">{label}</Text>
      <Text size="sm" fw={600}>{value}</Text>
    </div>
  );
}

function ElevationChart({ samples, reversed }: { samples: [number, number | null][]; reversed?: boolean }) {
  const pts = samples.filter((s) => s[1] != null) as [number, number][];
  if (pts.length < 2) return <Text size="xs" c="dimmed">For få punkter for profil.</Text>;
  const W = 320, H = 90, PAD = 2;
  const xs = pts.map((p) => p[0]);
  const zs = pts.map((p) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minZ = Math.min(...zs), maxZ = Math.max(...zs);
  const spanX = maxX - minX || 1, spanZ = maxZ - minZ || 1;
  const sx = (x: number) => {
    const t = (x - minX) / spanX;
    const tt = reversed ? 1 - t : t;
    return PAD + tt * (W - 2 * PAD);
  };
  const sy = (z: number) => PAD + (1 - (z - minZ) / spanZ) * (H - 2 * PAD);
  const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" ");
  const area = `${line} L${sx(maxX).toFixed(1)},${(H - PAD).toFixed(1)} L${sx(minX).toFixed(1)},${(H - PAD).toFixed(1)} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }} preserveAspectRatio="none">
      <path d={area} fill="#a5d8ff" opacity={0.6} />
      <path d={line} fill="none" stroke="#1971c2" strokeWidth={1.2} />
    </svg>
  );
}
