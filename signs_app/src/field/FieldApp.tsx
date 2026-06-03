import { useEffect, useRef, useState } from "react";
import {
  Badge, Button, Card, Center, Group, Image, Loader, SegmentedControl, Stack, Text, Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { api } from "../api";
import MapView from "../MapView";
import type { RouteListItem, RouteSummary, SessionUser, SignSite } from "../types";

const AREAS = [
  { value: "bre", label: "Breheimen" },
  { value: "fem", label: "Femundsmarka" },
  { value: "ron", label: "Rondane" },
];
const AREA_KEY = "dntfelt.area";

type View = "kart" | "bilder";

type UploadState = {
  key: string;
  name: string;
  previewUrl: string;
  status: "uploading" | "done" | "error";
  error?: string;
  geotagged?: boolean;
};

/** Get the current device position once (or null on denial/timeout). iOS Safari
 *  needs HTTPS + a user-gesture-triggered permission prompt. */
function getPosition(): Promise<{ lon: number; lat: number } | null> {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lon: p.coords.longitude, lat: p.coords.latitude }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 15000 },
    );
  });
}

export default function FieldApp() {
  const [me, setMe] = useState<SessionUser | null | undefined>(undefined);
  const [area, setArea] = useState<string>(() => localStorage.getItem(AREA_KEY) || "bre");
  const [view, setView] = useState<View>("kart");

  // photo upload
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // map data
  const [routes, setRoutes] = useState<RouteListItem[]>([]);
  const [routeSummaries, setRouteSummaries] = useState<Map<string, RouteSummary>>(new Map());
  const [sites, setSites] = useState<SignSite[]>([]);
  const [mapLoading, setMapLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);

  useEffect(() => {
    api.getMe()
      .then((u) => { setMe(u); if (u) api.setCurrentUser(u.email); })
      .catch(() => setMe(null));
  }, []);

  // Load routes + sign sites for the map (lazily, when the map is shown).
  useEffect(() => {
    if (!me || view !== "kart") return;
    let cancelled = false;
    setMapLoading(true);
    setSelectedIdx(null);
    Promise.all([api.getAreaRoutes(area), api.getCandidates(area)])
      .then(([summary, cands]) => {
        if (cancelled) return;
        const m = new Map<string, RouteSummary>();
        const items: RouteListItem[] = [];
        for (const s of summary.routes || []) {
          m.set(s.rutenummer, s);
          if (s.route_geometry || s.route_geometry_unmarked) {
            items.push({
              rutenummer: s.rutenummer,
              rutenavn: s.rutenavn ?? null,
              route_geometry: s.route_geometry,
              route_geometry_unmarked: s.route_geometry_unmarked,
            });
          }
        }
        setRoutes(items);
        setRouteSummaries(m);
        setSites(cands.sites);
      })
      .catch(() => { if (!cancelled) notifications.show({ color: "red", message: "Klarte ikke å laste kartdata." }); })
      .finally(() => { if (!cancelled) setMapLoading(false); });
    return () => { cancelled = true; };
  }, [me, view, area]);

  function chooseArea(v: string) {
    setArea(v);
    localStorage.setItem(AREA_KEY, v);
  }

  async function onFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const list = Array.from(files);
    setBusy(true);
    const pos = await getPosition();
    if (!pos) notifications.show({ color: "yellow", message: "Ingen GPS — bildene lastes opp uten plassering.", autoClose: 4000 });

    let ok = 0, failed = 0;
    for (const file of list) {
      const key = `${file.name}-${file.size}-${Math.round(performance.now())}-${Math.random().toString(36).slice(2, 7)}`;
      const previewUrl = URL.createObjectURL(file);
      setUploads((prev) => [{ key, name: file.name, previewUrl, status: "uploading" }, ...prev]);
      try {
        const photo = await api.uploadPhoto(area, file);
        let geotagged = false;
        if (pos) {
          try { await api.patchPhoto(photo.id, { lon: pos.lon, lat: pos.lat }); geotagged = true; } catch { /* best-effort */ }
        }
        ok += 1;
        setUploads((prev) => prev.map((u) => u.key === key ? { ...u, status: "done", geotagged } : u));
      } catch (e) {
        failed += 1;
        const msg = e instanceof Error ? e.message : String(e);
        setUploads((prev) => prev.map((u) => u.key === key ? { ...u, status: "error", error: msg } : u));
      }
    }
    setBusy(false);
    notifications.show({
      color: failed === 0 ? "teal" : ok === 0 ? "red" : "yellow",
      message: failed === 0 ? `${ok} bilde${ok === 1 ? "" : "r"} lastet opp${pos ? " med posisjon" : ""}.` : `${ok} lastet opp, ${failed} feilet.`,
      autoClose: 5000,
    });
    if (fileRef.current) fileRef.current.value = "";
  }

  if (me === undefined) return <Center mih="100vh"><Loader /></Center>;

  if (me === null) {
    const next = encodeURIComponent(window.location.pathname);
    return (
      <Center mih="100vh" p="lg">
        <Stack align="center" gap="md">
          <Title order={3}>DNT Felt</Title>
          <Text c="dimmed" ta="center">Logg inn for å bruke feltappen.</Text>
          <Button size="lg" component="a" href={`/api/v1/auth/login?next=${next}`}>Logg inn</Button>
        </Stack>
      </Center>
    );
  }

  const selectedSite = selectedIdx != null ? sites[selectedIdx] : null;

  return (
    <Stack gap={0} style={{ height: "100dvh", overflow: "hidden", background: "#f6f8fa" }}>
      <Group justify="space-between" wrap="nowrap" bg="brand.7" px="md" py="sm"
        style={{ paddingTop: "calc(env(safe-area-inset-top) + 10px)" }}>
        <Title order={4} c="white">DNT Felt</Title>
        <SegmentedControl
          size="xs"
          value={area}
          onChange={chooseArea}
          data={AREAS.map((a) => ({ value: a.value, label: a.label.slice(0, 3) }))}
        />
      </Group>

      {/* content */}
      <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
        {view === "kart" ? (
          <>
            <MapView
              routes={routes}
              routeSummaries={routeSummaries}
              sites={sites}
              selectedIdx={selectedIdx}
              onSelect={setSelectedIdx}
              baseLayer="topo4"
              focusedRoute={null}
              onFocusRoute={() => {}}
              areaCode={area}
              geolocate
            />
            {mapLoading && (
              <div style={{ position: "absolute", top: 10, left: "50%", transform: "translateX(-50%)", zIndex: 5 }}>
                <Badge color="gray" variant="filled" leftSection={<Loader size={10} color="white" />}>Laster kart…</Badge>
              </div>
            )}
            {selectedSite && (
              <Card withBorder padding="sm" radius="md" shadow="md"
                style={{ position: "absolute", left: 8, right: 8, bottom: 8, zIndex: 5 }}>
                <Group justify="space-between" wrap="nowrap" align="flex-start">
                  <div style={{ minWidth: 0 }}>
                    <Text fw={600} size="sm" truncate>{selectedSite.name || "(uten navn)"}</Text>
                    <Text size="xs" c="dimmed">
                      {(selectedSite.route_numbers || []).join(", ")} · {selectedSite.panels.length} skilt
                    </Text>
                  </div>
                  <Button size="compact-xs" variant="subtle" color="gray" onClick={() => setSelectedIdx(null)}>Lukk</Button>
                </Group>
                {selectedSite.panels.length > 0 && (
                  <Stack gap={2} mt={6}>
                    {selectedSite.panels.map((p, i) => (
                      <Text key={i} size="xs">
                        → {p.destination_name}
                        {p.distance_km_displayed != null && <span style={{ color: "#666" }}> · {p.distance_km_displayed} km</span>}
                      </Text>
                    ))}
                  </Stack>
                )}
              </Card>
            )}
          </>
        ) : (
          <Stack gap="md" p="md" style={{ height: "100%", overflowY: "auto" }}>
            <input ref={fileRef} type="file" accept="image/*" multiple style={{ display: "none" }} onChange={(e) => onFiles(e.target.files)} />
            <Button size="xl" fullWidth loading={busy} onClick={() => fileRef.current?.click()} styles={{ root: { height: 72, fontSize: 18 } }}>
              Ta / velg bilde
            </Button>
            <Text size="xs" c="dimmed" ta="center">
              Bildet lastes opp til {AREAS.find((a) => a.value === area)?.label} med GPS-posisjon.
            </Text>
            {uploads.map((u) => (
              <Card key={u.key} withBorder padding="xs" radius="md">
                <Group gap="sm" wrap="nowrap">
                  <Image src={u.previewUrl} w={56} h={56} radius="sm" fit="cover" alt="" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Text size="xs" truncate>{u.name}</Text>
                    {u.status === "uploading" && <Group gap={6}><Loader size="xs" /><Text size="xs" c="dimmed">Laster opp…</Text></Group>}
                    {u.status === "done" && <Badge size="sm" color="teal" variant="light">{u.geotagged ? "Lastet opp ✓ (m/posisjon)" : "Lastet opp ✓"}</Badge>}
                    {u.status === "error" && <Badge size="sm" color="red" variant="light" title={u.error}>Feilet</Badge>}
                  </div>
                </Group>
              </Card>
            ))}
          </Stack>
        )}
      </div>

      {/* bottom nav */}
      <Group gap={0} grow style={{ borderTop: "1px solid #dde3ea", background: "#fff", paddingBottom: "env(safe-area-inset-bottom)" }}>
        <Button variant={view === "kart" ? "filled" : "subtle"} radius={0} h={52} onClick={() => setView("kart")}>🗺 Kart</Button>
        <Button variant={view === "bilder" ? "filled" : "subtle"} radius={0} h={52} onClick={() => setView("bilder")}>📷 Bilder</Button>
      </Group>
    </Stack>
  );
}
