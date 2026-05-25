# Gjennomgang: Rutene fjernes ved valg + zoom overstyres ved mouse-over

## Oppsummering

To feil er rapportert: (1) de andre rutene forsvinner når en rute er valgt, (2) zoomnivå overstyres ved mouse-over. Nedenfor er identifiserte årsaker og plan for retting. **Ingen kodeendringer er gjort i denne gjennomgangen.**

---

## Feil 1: De andre rutene fjernes når en rute er valgt

### Mulige årsaker

**A) Links-laget erstattes med kun valgt rutes lenker**

- **Hvor:** [MapView.tsx](changeset_editor/frontend/src/components/MapView.tsx) – effekt som laster segmenter/lenker ved valgt rute (ca. 2203–2235).
- **Hva som skjer:** Når `routeNumber` er satt kalles `api.getRouteLinks(routeNumber, ...)` og resultatet settes med `setLinksData({ type: 'FeatureCollection', features: filteredFeatures })`. Da inneholder `linksData` bare lenker for den valgte ruten.
- **Konsekvens:** Lenker-overlayet (teal) viser kun den valgte rutens lenker. Alle andre lenker/ruter i view forsvinner fra dette laget. Hvis brukeren oppfatter «ruter» som det som vises i Lenker-laget (lenker med tilhørende ruteinfo), vil det oppleves som at «de andre rutene fjernes».
- **Retting:** Ved valgt rute: ikke erstatte `linksData` med kun rutens lenker. Behold siste bbox-baserte `linksData` (alle lenker i view) og bruk eksisterende `highlightRouteLinks`-logikk for å markere den valgte rutens lenker (som ved hover). Da forblir alle lenker synlige og valgt rute fremheves.

**B) At `routesInView` likevel erstattes (grått rute-lag)**

- **Hvor:** Samme rute-laste-effekt (ca. 1819–2071).
- **Hva som skjer:** Vi har `skipLoadBecauseRouteSelected = routeNumber && routesInView?.features?.length` og kjører ikke initial load når det er sant. Men effekten har `routesInView` i dependency-array. Hvis det oppstår en re-render der `routesInView` midlertidig er `null` eller tom (f.eks. pga. rekkefølge av oppdateringer eller annen state), vil `skipLoadBecauseRouteSelected` bli false og vi planlegge en ny last som til slutt kaller `setRoutesInView` og erstatter innholdet.
- **Retting:** Stramme inn når vi skal kjøre initial load: ikke kjøre `loadRoutesInView` når `routeNumber` er satt, uavhengig av `routesInView` (unntak: f.eks. første gang etter lasting med `?route=X` der `routesInView` er null – da kan man la én initial load kjøre med `getBounds()`). Alternativt bruke en ref (f.eks. `hasLoadedRoutesWithRouteSelected`) for å unngå å overskrive `routesInView` etter at bruker har valgt rute.

**C) Rydding av `routesInView` ved visse betingelser**

- **Hvor:** Samme effekt, ca. 1823–1826: `if (!showLinks && !routeNumber) { setRoutesInView(null); return; }`.
- **Hva som skjer:** Hvis brukeren har «Lenker» av (showLinks = false) og deretter velger en rute (routeNumber satt), vil vi ikke kalle `setRoutesInView(null)`. Men hvis det finnes andre steder som setter `showLinks` til false når rute velges, eller om det er race mellom state-oppdateringer, kan man teoretisk havne i en tilstand der rute-last ikke kjører og `routesInView` tidligere ble null. Verdt å dobbeltsjekke at ingen andre koder setter `routesInView` til null eller tom når `routeNumber` er satt.

---

## Feil 2: Zoomnivå overstyres ved mouse-over

### Mulige årsaker

**A) fitBounds ved valgt område (selectedArea)**

- **Hvor:** [MapView.tsx](changeset_editor/frontend/src/components/MapView.tsx) ca. 1992–1999.
- **Hva som skjer:** Etter at ruter er lastet for valgt område (`selectedArea`), kalles `mapRef.current.fitBounds(bbox, { padding: [50, 50] })`. Det endrer både senter og zoom slik at alle lastede ruter er innenfor view.
- **Konsekvens:** Hvis «mouse-over» oppleves i sammenheng med at bruker velger område (f.eks. fra en dropdown eller et element som trigges ved hover), eller at denne effekten kjører på nytt ved hover pga. re-render, vil zoom kunne overstyres.
- **Retting:** Fjerne eller betinge denne `fitBounds`-kallen: enten ikke sentrere/zoome automatisk når ruter lastes for område, eller bare kjøre den én gang ved første lasting for området (ikke ved senere re-renders/hover).

**B) MapContainer center/zoom resettes ved re-render**

- **Hvor:** [MapView.tsx](changeset_editor/frontend/src/components/MapView.tsx) ca. 3351–3355: `<MapContainer center={[61.5, 8.5]} zoom={7} ...>`.
- **Hva som skjer:** I react-leaflet kan bruk av kontrollerte `center`/`zoom`-props føre til at kartet synkroniseres til disse verdiene ved oppdateringer. Ved mouse-over kan state endres (f.eks. tooltip, highlight), MapView re-rendres, og MapContainer kan da potensielt resette view til `center={[61.5, 8.5]}` og `zoom={7}`.
- **Retting:** Gjøre kartet ukontrollert etter første mount: bruke kun `center` og `zoom` som initialverdier (f.eks. via `useRef` for «har mountet» og ikke sende dem inn på senere render), eller bruke react-leaflet sin anbefalte måte for «uncontrolled» map slik at brukerens pan/zoom ikke overskrives ved re-render.

**C) Annen zoom/pan-trigger ved hover**

- **Hvor:** Ukjent – ingen andre `fitBounds`, `flyTo` eller `setView` i app-koden (kun i test-setup).
- **Hva som skjer:** Mouse-over på lenker (LinksLayer) trigger highlight og tooltip (ca. 847–941). Disse endrer ikke direkte zoom, men kan indirekte føre til re-render som igjen trigger (A) eller (B).
- **Retting:** Etter at (A) og (B) er adressert: hvis problemet vedvarer, må man med logging eller breakpoints bekrefte om zoom endres i samme tick som en hover-event og spore hvilken kode som kaller view-endring.

---

## Plan for retting (uten kodeendring nå)

1. **Ruter/linker som forsvinner**
   - **Prioritet 1:** Vurdere (1A): Ved valgt rute ikke erstatte `linksData` med kun rutens lenker; behold bbox-lenker og bruk highlight for valgt rute (som ved hover).
   - **Prioritet 2:** Stramme inn (1B): Sikre at vi aldri kjører `loadRoutesInView` som overskriver `routesInView` når `routeNumber` er satt (unntak evt. kun ved første last for `?route=X`), eventuelt med ref for «har lastet med valgt rute».
   - **Prioritet 3:** Gå gjennom (1C) og verifisere at ingen andre steder nuller/overskriver `routesInView` når rute er valgt.

2. **Zoom overstyres ved mouse-over**
   - **Prioritet 1:** Undersøke (2B): Gjøre MapContainer ukontrollert mht. center/zoom etter mount (kun initialverdier), slik at re-render ikke resetter zoom.
   - **Prioritet 2:** Justere (2A): Fjerne eller begrense `fitBounds` ved `selectedArea` til én gang ved første lasting, så ikke senere re-renders (eller hover) trigger zoom-endring.
   - **Prioritet 3:** Hvis problemet er der etter (2A)+(2B): Spore (2C) med logging for å finne nøyaktig trigger.

3. **Verifisering**
   - Etter endringer: Test både «velg rute via URL» og «velg rute ved klikk» og sjekk at alle ruter/lenker i view forblir synlige og at zoom ikke endres ved mouse-over.

---

## Status etter rettinger

- **1A:** Implementert – `linksData` erstattes ikke med kun valgt rutes lenker; bbox-lenker beholdes, `highlightRouteLinks(selectedRouteNumber)` brukes. `selectedRouteNumber` er lagt i dependency-arrayet til LinksLayer-effekten.
- **1B:** Implementert – `skipLoadBecauseRouteSelected = routeNumber && (routesInView?.features?.length ?? 0) > 0`.
- **1C:** Verifisert – `setRoutesInView(null)` kun i `if (!showLinks && !routeNumber)`.
- **2A:** Implementert – `fitBounds` ved `selectedArea` fjernet.
- **2B:** Implementert – `INITIAL_MAP_CENTER` og `INITIAL_MAP_ZOOM` for MapContainer.
- **2C:** Vurderes etter manuell test.
gt.
- **2A:** Implementert – `fitBounds` ved `selectedArea` er fjernet (kommentar i kode ca. 2001).
- **2B:** Implementert – `INITIAL_MAP_CENTER` og `INITIAL_MAP_ZOOM` brukes som stabile initialverdier for `MapContainer`.
- **2C:** Vurderes etter manuell test av Feil 2.
