# Evaluering av Stiflyt MCP og REST API

Kort vurdering av dagens API og forslag til utvidelser som gjør at en AI-assistent (eller andre klienter) kan svare på flere brukerspørsmål.

---

## 1. Er REST APIet greit nok?

**Ja.** REST APIet er ryddig, godt dokumentert og dekker det det er bygget for:

- **Ruter:** liste, enkelt, complete, segmenter, lenker, statistikk, områder, bulk, validering.
- **Søk:** `search/places` på stedsnavn, ruteinfopunkt og ruter.
- **Ankere/endepunkter:** ankernoder, navn, placename-kandidater, upsert av navn.
- **Skilt:** rapport, mangler, produksjon.
- **Geometri/matrikkel:** eiere langs linje, punkt matrikkelenhet.
- **Changesets:** CRUD, events, validering, diff/effective GeoJSON, publish.
- **Editor:** snap targets, health.

MCP-serveren eksponerer disse 1:1 som verktøy – ingen backend-endepunkter mangler i MCP. REST-designet (ressurser, query-parametre, feilkoder) er fornuftig; ingen grunn til å rive opp selve APIet.

---

## 2. Hva MCP gjør det mulig å svare på i dag

Med dagens verktøy kan man blant annet:

- Liste ruter per område (prefix), vedlikeholdsansvarlig eller bbox.
- Hente enkeltruer, full «complete»-rute med geometri og endepunkter.
- Søke steder og ruter (`search_places`).
- Få statistikk (antall ruter, total km, distinct km) per prefix/bbox/vedlikeholdsansvarlig.
- Se ankernoder og navn for en rute, og kandidater for ankernavn.
- Få skiltrapporter og produksjon.
- Validere ruter og changesets.

**Eksempler på spørsmål som fungerer:** «Ruter i Breheimen», «hvor lang er bre20», «ruter til Arentzbu», «km merket i Jotunheimen», «ruter fra Tynset», «liste områder og km».

---

## 3. Begrensninger som kom fram i bruk

- **«Ruter mellom to steder»**  
  Ingen direkte «rute mellom A og B». Man må selv: søke A og B, liste ruter i området, sammenligne segmenter/ankere og slutte at det ikke finnes én dedikert rute, eller at man må kombinere ruter. Det krever mange kall og tolkning.

- **«Avstand mellom to steder»**  
  Kun luftlinje mulig (koordinater fra `search_places`). Ingen gang-/ruteavstand med mindre det finnes én rute med begge som endepunkter.

- **«Flere ruter mellom to hytter?»**  
  Krever at man kjenner alle ruter som har de to stedene som endepunkter. I dag er `from_name`/`to_name` ofte null, og det finnes ikke filter/søk på endepunkt. Vanskelig å svare sikkert uten å hente mye og resonnere.

- **Status på ruter**  
  Ingen felt for «status» (åpen/stengt/omlegging/sesong) eller vedlikeholdsstatus. Man kan ikke svare på «er bre10 åpen nå?».

- **Hytter**  
  Ingen egen ressurs for hytter (DNT eller andre). Hytter opptrer bare som stedsnavn eller ruteinfopunkt i søk, og eventuelt som ankernavn på ruter. Man kan ikke liste «hytter i område X» eller «hytter med overnatting» uten å tolke generelle stedsnavn.

- **Ruteplanlegging**  
  Ingen sti/ruteberegning på nettverket (links/segmenter). Man kan ikke få «rute fra Fondsbu til Leirvassbu» som geometri + lengde.

Disse begrensningene handler mindre om «er REST APIet greit» og mer om **manglende domene-data og ett-til-to nye endepunkter**.

---

## 4. Foreslåtte forbedringer (prioritert)

### 4.1 Ruteplanlegger-API (høy verdi)

**Formål:** Svare på «hvor langt er det fra A til B langs merkede ruter?» og «hvilke ruter går mellom to steder?».

Forslag:

- **`POST /api/v1/route-plan`** (eller `/api/v1/routing`):
  - Input: to steder (stedsnavn-id, ruteinfopunkt-id, eller koordinater), evt. område/prefix.
  - Output:
    - `distance_m`: estimert ganglengde.
    - `route_ids`: rutenummer som inngår (rekkefølge eller som mengde).
    - `geometry`: valgfri samlet linje (GeoJSON).
    - `legs`: evt. etapper (f.eks. per rute).

Implementasjon kan være:

- Graf basert på eksisterende links/ankernoder; korteste-vei (f.eks. Dijkstra) på dette nettverket.
- Alternativt: kun «direkte» – finn ruter som har begge steder som endepunkter/ankere, og returner lengde + rutenummer. Enklere, men dekker ikke kombinasjoner av flere ruter.

Selv en enkel versjon («finn ruter som har begge punkter som ankere») som eget endepunkt vil gjøre MCP-verktøyet mye mer nyttig for planlegging.

**MCP:** Ett verktøy f.eks. `route_plan(from_place_id_or_coords, to_place_id_or_coords, options)` som kaller dette endepunktet.

---

### 4.2 Status på ruter (medium verdi)

**Formål:** Svare på «er ruten åpen?», «er den stengt pga. vedlikehold?».

Forslag:

- Utvid rute-modell (view/API) med valgfrie felt, f.eks.:
  - `status`: `open | closed | maintenance | seasonal | unknown`
  - `status_updated_at`: ISO-dato.
  - `status_note`: fri tekst (vises i API og MCP).

Kilde kan være manuell redigering, DNT API (hvis tilgjengelig) eller egen mikrotjeneste som oppdaterer status.

**REST:** Felt inkludert i `GET /api/v1/routes/{rutenummer}` og i listesvar.  
**MCP:** Ingen nye verktøy nødvendig; eksisterende `get_route` og `list_routes` får mer informasjon.

---

### 4.3 Integrasjon med hytter (medium–høy verdi)

**Formål:** «Hytter i Rondane», «hvilke hytter har bre-senger?», «ruter som ender ved en DNT-hytte».

Forslag A – **egen hytte-ressurs i Stiflyt:**

- **`GET /api/v1/huts`**  
  Query: `bbox`, `prefix` (område), `has_overnight`, evt. `organisation`.  
  Response: liste med id, navn, koordinater, evt. lenke til DNT, overnatting ja/nei.
- **`GET /api/v1/huts/{id}`**  
  Detaljer + evt. «ruter som har denne hytten som endepunkt» (hvis dere bygger den koblingen).

Data kan komme fra DNT (API/CSV/GeoJSON) eller egen registerfil; viktigste er at Stiflyt eksponerer en stabil liste med koordinater og navn.

Forslag B – **kun kobling mot ruter:**

- I rute-API: felt `from_hut_id` / `to_hut_id` (eller liste over `hut_ids` langs ruten) hvis dere matcher ankere mot et hytteregister. Da kan man filtrere «ruter som går til hytte X» uten eget `/huts`-endepunkt i første omgang.

**MCP:** Verktøy `list_huts(bbox, prefix, ...)` og evt. `get_hut(id)`; eventuelt utvidelse av `get_route` / `list_routes` med hytte-info.

---

### 4.4 Søk/filter på endepunkter (rask forbedring)

**Formål:** «Ruter som går til Leirvassbu» uten å hente alle ruter og filtrere selv.

Forslag:

- **`GET /api/v1/routes?endpoint_name=Leirvassbu`**  
  eller  
- **`GET /api/v1/routes?from_name=...&to_name=...`**  
  (substring eller eksakt mot `from_name`/`to_name` i view).

Krever at view eller backend støtter slike filtre (og at `from_name`/`to_name` er godt fylt).  
**MCP:** Samme `list_routes` med nye parametere; ingen nytt verktøy nødvendig.

---

### 4.5 Avstand mellom to punkter langs nettverket (komplement til ruteplanlegging)

**Formål:** «Hvor langt er det fra Sota til Nørdstedalseter langs merkede ruter?»

Kan leveres som del av ruteplanlegger-APIet (avstand i `distance_m`). Alternativt et enkelt endepunkt:

- **`POST /api/v1/distance`**  
  Body: `{ "from": { "lat", "lon } | { "place_id": "..." }, "to": { ... } }`  
  Response: `{ "distance_m": ..., "route_ids": [...] }`  
  (snapp til nærmeste lenker/anker og summer lengde).

Dette gjør det mulig å svare både på «hvor langt» og «hvilke ruter» i ett kall.

---

## 5. Oppsummering

| Tema | Vurdering | Forslag |
|------|-----------|--------|
| **REST API** | Greit nok, ryddig | Behold design; utvid med nye ressurser/parametre der det trengs. |
| **MCP** | God dekning av backend | Legg til 1–2 verktøy når ruteplanlegging/hytter kommer (f.eks. `route_plan`, `list_huts`). |
| **Ruteplanlegging** | Mangler | Nytt endepunkt (routing/route-plan) + MCP-verktøy. |
| **Status ruter** | Mangler | Valgfrie felter på rute (status, note, updated_at). |
| **Hytter** | Kun som steder i dag | Eget `/huts`-API og/eller kobling fra ruter til hytter + MCP. |
| **Søk på endepunkter** | Vanskelig i dag | Query-parametre `endpoint_name` / `from_name` / `to_name` på `GET /routes`. |

REST APIet trenger ikke å byttes ut; det som mangler er noen få, målrettede utvidelser (ruteplanlegging, status, hytter, endepunkt-filter) slik at både MCP og andre klienter kan svare på flere naturlige brukerspørsmål uten å bygge kompleks logikk utenfor APIet.
