import { useEffect, useRef, useState } from "react";
import {
  Badge, Button, Card, Center, Group, Image, Loader, SegmentedControl, Stack, Text, Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { api } from "../api";
import type { SessionUser } from "../types";

const AREAS = [
  { value: "bre", label: "Breheimen" },
  { value: "fem", label: "Femundsmarka" },
  { value: "ron", label: "Rondane" },
];
const AREA_KEY = "dntfelt.area";

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
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    api.getMe()
      .then((u) => { setMe(u); if (u) api.setCurrentUser(u.email); })
      .catch(() => setMe(null));
  }, []);

  function chooseArea(v: string) {
    setArea(v);
    localStorage.setItem(AREA_KEY, v);
  }

  async function onFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const list = Array.from(files);
    setBusy(true);

    // One position fix for the whole batch — photos are taken at ~one spot.
    const pos = await getPosition();
    if (!pos) {
      notifications.show({ color: "yellow", message: "Ingen GPS-posisjon — bildene lastes opp uten plassering.", autoClose: 4000 });
    }

    let ok = 0;
    let failed = 0;
    for (const file of list) {
      const key = `${file.name}-${file.size}-${Math.round(performance.now())}-${Math.random().toString(36).slice(2, 7)}`;
      const previewUrl = URL.createObjectURL(file);
      setUploads((prev) => [{ key, name: file.name, previewUrl, status: "uploading" }, ...prev]);
      try {
        const photo = await api.uploadPhoto(area, file);
        let geotagged = false;
        if (pos) {
          try { await api.patchPhoto(photo.id, { lon: pos.lon, lat: pos.lat }); geotagged = true; }
          catch { /* geotag is best-effort; photo is uploaded regardless */ }
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
      message: failed === 0
        ? `${ok} bilde${ok === 1 ? "" : "r"} lastet opp${pos ? " med posisjon" : ""}.`
        : `${ok} lastet opp, ${failed} feilet.`,
      autoClose: 5000,
    });
    if (fileRef.current) fileRef.current.value = "";  // allow re-picking the same file
  }

  if (me === undefined) {
    return <Center mih="100vh"><Loader /></Center>;
  }

  if (me === null) {
    const next = encodeURIComponent(window.location.pathname);
    return (
      <Center mih="100vh" p="lg">
        <Stack align="center" gap="md">
          <Title order={3}>DNT Felt</Title>
          <Text c="dimmed" ta="center">Logg inn for å laste opp bilder fra felt.</Text>
          <Button size="lg" component="a" href={`/api/v1/auth/login?next=${next}`}>Logg inn</Button>
        </Stack>
      </Center>
    );
  }

  return (
    <Stack gap={0} mih="100vh" style={{ background: "#f6f8fa" }}>
      <Group justify="space-between" wrap="nowrap" bg="brand.7" px="md" py="sm"
        style={{ paddingTop: "calc(env(safe-area-inset-top) + 10px)" }}>
        <Title order={4} c="white">📷 DNT Felt</Title>
        <Text size="xs" c="white" opacity={0.85} style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {me.email}
        </Text>
      </Group>

      <Stack gap="md" p="md" style={{ flex: 1 }}>
        <div>
          <Text size="sm" fw={500} mb={4}>Område</Text>
          <SegmentedControl fullWidth value={area} onChange={chooseArea} data={AREAS} />
        </div>

        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          multiple
          style={{ display: "none" }}
          onChange={(e) => onFiles(e.target.files)}
        />
        <Button
          size="xl"
          fullWidth
          loading={busy}
          onClick={() => fileRef.current?.click()}
          styles={{ root: { height: 72, fontSize: 18 } }}
        >
          Ta / velg bilde
        </Button>
        <Text size="xs" c="dimmed" ta="center">
          Bildet lastes opp til {AREAS.find((a) => a.value === area)?.label} med GPS-posisjon.
        </Text>

        {uploads.length > 0 && (
          <Stack gap="xs">
            {uploads.map((u) => (
              <Card key={u.key} withBorder padding="xs" radius="md">
                <Group gap="sm" wrap="nowrap">
                  <Image src={u.previewUrl} w={56} h={56} radius="sm" fit="cover" alt="" />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Text size="xs" truncate>{u.name}</Text>
                    {u.status === "uploading" && <Group gap={6}><Loader size="xs" /><Text size="xs" c="dimmed">Laster opp…</Text></Group>}
                    {u.status === "done" && (
                      <Badge size="sm" color="teal" variant="light">
                        {u.geotagged ? "Lastet opp ✓ (m/posisjon)" : "Lastet opp ✓"}
                      </Badge>
                    )}
                    {u.status === "error" && <Badge size="sm" color="red" variant="light" title={u.error}>Feilet</Badge>}
                  </div>
                </Group>
              </Card>
            ))}
          </Stack>
        )}
      </Stack>
    </Stack>
  );
}
