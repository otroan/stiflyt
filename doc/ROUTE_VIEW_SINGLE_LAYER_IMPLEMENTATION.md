# Implementasjonsforslag: Én linje for rute med modus (rute / segmenter / lenker)

## Mål

- Tegne ruta **én gang**; ingen duplisering av rød rute + violette segmenter + grønne lenker.
- Forskjellen mellom rute, segmenter og lenker skal være: **markører** (grenser) og **hover/popup/valg** (hva som vises og velges).
- Én «innholdslag» som viser enten rutegeometri, segmenter eller lenker avhengig av valgt modus.

---

## 1. Ny state: visningsmodus for valgt rute

**App.tsx**

- Legg til: `routeViewMode: 'route' | 'segments' | 'links'` (default `'route'`).
- Når `routeNumber` er satt: bruk `routeViewMode` til å bestemme hva som tegnes.
- Erstatt/utvid gjensidig utelukkelse: i stedet for to bools `showSegments` og `showLinks`, kan vi beholde dem for bakoverkompatibilitet **eller** erstatte med én `routeViewMode`. Forslag: **erstatte** `showSegments` og `showLinks` for **valgt rute** med `routeViewMode`, slik at:
  - `routeViewMode === 'route'` → vis kun rute (rød linje).
  - `routeViewMode === 'segments'` → vis segmenter (violette linjer, segmentgrenser som markører).
  - `routeViewMode === 'links'` → vis lenker (teal linjer, linkgrenser som markører).
- Når **ingen** rute er valgt: beholde nåværende «Lenker» (bbox-last) som eget lag; da er det ikke «route view» men «links in view». Da kan vi beholde en boolean `showLinks` for bbox-lenker, og `routeViewMode` gjelder bare når `routeNumber != null`.

**Konkret state**

- `routeViewMode: 'route' | 'segments' | 'links'` (default `'route'`).
- Ved ruteskift: sett f.eks. `routeViewMode = 'route'` (eller behold forrige).
- Sidebar/MapView sender ned `routeViewMode` og `onRouteViewModeChange`.

---

## 2. Ét «route content»-lag i MapView

**MapView.tsx**

I dag:

- **Rød rute**: egen `useEffect` som tegner `routeGeometry` i `routePane` (alltid når `routeGeometry && routeNumber === selectedRouteNumber`).
- **Segmenter**: `SegmentsLayer` med `segmentsData` (når `showSegments`).
- **Lenker**: `LinksLayer` i LayersControl med `linksData` (når `showLinks` for rute, eller bbox-lenker).

**Endring:**

- **Én** lagkomponent (eller én `useEffect` som bygger ett Leaflet GeoJSON-lag) som får:
  - `mode: 'route' | 'segments' | 'links'`
  - `routeGeometry` (for mode `'route'`)
  - `segmentsData` (for mode `'segments'`)
  - `linksData` (for mode `'links'`)

Og som **kun** tegner det som hører til aktiv modus:

- `mode === 'route'`: tegn `routeGeometry` som én linje (rød, weight 6). Ingen segment-/linklinjer.
- `mode === 'segments'`: tegn `segmentsData` (violette linjer, valgt = blå). **Tegn ikke** den røde rutelinjen i tillegg.
- `mode === 'links'`: tegn `linksData` for **valgt rute** (teal, stiplet). **Tegn ikke** rød rute eller segmenter.

Dermed tegnes samme strekning aldri to ganger: enten rute, eller segmenter, eller lenker.

**Teknisk**

- Erstatt den nåværende «alltid rød rute»-effekten med en som sier: «Tegn rute kun når `routeViewMode === 'route'`».
- Når `routeViewMode === 'segments'`: bruk samme logikk som i dagens `SegmentsLayer` (violette linjer fra `segmentsData`), men **uten** at den røde rute-linjen også tegnes.
- Når `routeViewMode === 'links'` og det finnes `linksData` for ruten: tegn kun link-linjer for denne ruten (stilet som i dag); ikke rød rute og ikke segmenter.

Alternativt kan du lage **én** komponent `RouteContentLayer` som tar `mode`, `routeGeometry`, `segmentsData`, `linksData`, `selectedFeatureId`, `selectedFeatureIds`, `onFeatureSelect`, og som inni seg velger én av de tre datasettene og én style-funksjon (rød / violet / teal). Da har du bokstavelig ett lag som bytter innhold.

---

## 3. Markører avhenger av modus

Eksisterende kode tegner allerede sirkler på segment-start/slutt når segmenter vises. Behold og begrens til aktiv modus:

- **`route`**: markører kun på rutens start og slutt (evt. ingen markører).
- **`segments`**: markører på alle segmentgrenser (som i dag).
- **`links`**: markører på linkgrenser (knutepunkter); kan gjenbruke/utvide dagens endepunktslogikk for lenker.

Sørg for at markør-effekten som legger på sirkler, kun kjører for den modusen som er valgt (slik at du ikke får segment-markører når vi kun viser lenker, osv.).

---

## 4. Sidebar: velg modus (Rute / Segmenter / Lenker)

**InfoPanel.tsx**

I stedet for kun avkrysning «Vis segmenter på kartet»:

- Når `routeNumber` er satt: vis en **modusvelger** for ruteinnhold, f.eks.:
  - Radioknapper eller dropdown: **«Rute»** | **«Segmenter»** | **«Lenker»**.
- Når bruker velger «Segmenter»:
  - Sett `routeViewMode = 'segments'`.
  - Vis segmentlisten under (som i dag).
  - Kartet viser violette segmentlinjer + segmentmarkører; ingen rød rute.
- Når bruker velger «Lenker»:
  - Sett `routeViewMode = 'links'`.
  - Evt. vis en liste over linker for ruten (kan komme i en senere iterasjon).
  - Kartet viser teal link-linjer + link-markører.
- Når bruker velger «Rute»:
  - Sett `routeViewMode = 'route'`.
  - Kartet viser kun den røde rutelinjen; ingen segment-/linklinjer.

Dette erstatter behovet for å «skru på segmenter» og «skru på lenker» samtidig som den røde ruta alltid ligger under; nå er det én av tre visninger.

---

## 5. Datalasting (uendret i prinsippet)

- **Rute**: `getRoute(rutenummer, true)` → `routeGeometry` (som i dag).
- **Segmenter**: `getRouteSegments(rutenummer, true)` → `segmentsData` (som i dag). Kan lastes når bruker velger modus «Segmenter» (lazy) eller ved rutevalg (eager); lazy forenkler og sparer kall.
- **Lenker**: for valgt rute, `getRouteLinks(rutenummer, true)` → `linksData` for ruten. Allerede brukt; behold.

Ingen endring i API-kall, bare **når** du tegner hva: du tegner kun det som `routeViewMode` tilsier.

---

## 6. Lenker uten valgt rute (bbox)

Når **ingen** rute er valgt, kan «Lenker» fortsatt vise lenker i viewport (bbox). Da gjelder ikke `routeViewMode`; det er et eget «links by bbox»-lag. Logikk:

- Hvis `routeNumber == null`: bruk eksisterende bbox-lenker og `showLinks` (eller eget flagg) for å vise/skjule det laget.
- Hvis `routeNumber != null`: bruk `routeViewMode`; ved `'links'` vis link-laget for ruten (én tegning), og ikke rød rute eller segmenter.

Dermed unngår du duplisering både for valgt rute og for bbox-lenker.

---

## 7. Kort steg-for-steg

1. **App**: Innfør `routeViewMode` og `onRouteViewModeChange`. Valgfritt: fjern `showSegments`/`showLinks` for valgt rute og bruk kun `routeViewMode`; behold `showLinks` for bbox-tilfelle.
2. **MapView**:
   - Tegn rød rute **kun** når `routeViewMode === 'route'`.
   - Når `routeViewMode === 'segments'`: tegn kun segmentlaget (som i dagens SegmentsLayer), ikke rute.
   - Når `routeViewMode === 'links'` og rute valgt: tegn kun linklaget for ruten, ikke rute eller segmenter.
   - Samle dette gjerne i ett «route content»-lag som bytter data og style ut fra `routeViewMode`.
3. **Markører**: Begrens segment-/link-markører til å kun tegnes når modus er henholdsvis `segments` eller `links`; evt. rute start/slutt kun i `route`.
4. **InfoPanel**: Erstatt «Vis segmenter»-avkrysning med modusvelger (Rute / Segmenter / Lenker) når `routeNumber` er satt; oppdater segmentlisten til å vises når modus er «Segmenter».
5. **Fjern** dobbel tegning: sikre at aldri både rød rute og violette segmenter (eller teal lenker) tegnes samtidig for samme rute.

---

## 8. Fordeler

- Ruta tegnes aldri flere ganger for samme visning.
- Tydelig modus: bruker ser enten rute, eller segmenter, eller lenker.
- Enklere mental modell: én «innholdsmodus» og én lagkilde av gangen.
- Lettere å utvide med kun markører og hover uten å introdusere nye linjelag.
