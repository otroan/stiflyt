# Rute Validering og Repair Verktøy med Overlay-løsning

## Dokumentoversikt

Dette dokumentet beskriver arkitekturen, designet og implementeringsplanen for et komplett system for rutevalidering og repair med overlay-løsning. Systemet lar brukere identifisere feil i ruter, gjøre endringer lokalt via et overlay-lag, og generere rapporter for kartverket.

**Versjon:** 1.0
**Dato:** 2024-01-15
**Status:** Planlegging

---

## 1. Oversikt

### 1.1 Problemstilling

Ruter i turrutebasen har ofte feil:
- Segmenter henger ikke sammen (gaps)
- Feil metadata (manglende rutenummer, feil tilknytning)
- Løse ender (disconnected segments)
- MultiLineString-geometrier når LineString er forventet

Kartverket oppdaterer kilden ukentlig, men det tar lang tid å få endringer gjennomført. I mellomtiden trenger vi:
- Mulighet til å gjøre lokale endringer
- Spore alle endringer (git-lignende log)
- Generere rapporter for kartverket
- Revert endringer hvis nødvendig
- Automatisk rebuild av link-topologi for berørte ruter

### 1.2 Løsning

**Overlay-lag arkitektur:**
- Overlay-tabeller som lagrer endringer uten å modifisere originale data
- Views som kombinerer originale data + overlay
- Change log for å spore alle endringer
- Inkremetell build-links for å oppdatere topologi kun for berørte ruter
- Diff/rapport-generering for kartverket

**Hovedkomponenter:**
1. **Overlay-lag**: Database-tabeller for å lagre endringer
2. **Change log**: Git-lignende log for å spore endringer
3. **Validering**: Eksisterende validator-system utvidet
4. **Repair-verktøy**: Frontend og API for å gjøre endringer
5. **Rapport-generering**: Diff og rapporter for kartverket

---

## 2. Arkitektur

### 2.1 Systemarkitektur

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Route Viewer │  │  Validation  │  │  Change Log   │   │
│  │   & Editor   │  │     Tab      │  │     View       │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
└─────────┼─────────────────┼──────────────────┼────────────┘
          │                 │                  │
          └─────────────────┼──────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────┐
│                    REST API (FastAPI)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │   Routes     │  │  Validation  │  │   Changes    │   │
│  │  Endpoints   │  │  Endpoints   │  │  Endpoints   │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
└─────────┼─────────────────┼──────────────────┼────────────┘
          │                 │                  │
          └─────────────────┼──────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────┐
│                  Business Logic Layer                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Validators  │  │  Overlay      │  │  Change Log   │   │
│  │   Service    │  │   Service    │  │   Service     │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Impact      │  │  Report       │  │  Build Links │   │
│  │  Analysis    │  │  Generator    │  │   Service     │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
└─────────┼─────────────────┼──────────────────┼────────────┘
          │                 │                  │
          └─────────────────┼──────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────┐
│                    Database Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Original    │  │   Overlay     │  │  Change Log   │   │
│  │   Tables     │  │   Tables      │  │   Table       │   │
│  │              │  │               │  │               │   │
│  │ fotrute      │  │ fotruteinfo_  │  │ change_log    │   │
│  │ fotruteinfo  │  │   overlay     │  │               │   │
│  │ links        │  │ fotrute_      │  │               │   │
│  │ nodes        │  │   overlay     │  │               │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                 │                  │           │
│         └─────────────────┼──────────────────┘           │
│                           │                              │
│         ┌─────────────────▼──────────────────┐          │
│         │        Merged Views                 │          │
│         │  fotruteinfo_merged                 │          │
│         │  fotrute_merged                     │          │
│         └─────────────────────────────────────┘          │
└──────────────────────────────────────────────────────────┘
```

### 2.2 Dataflyt

**Les-operasjoner:**
1. Frontend ber om rutedata
2. API henter fra merged views (original + overlay)
3. Overlay har prioritet over original
4. Data returneres til frontend

**Skrive-operasjoner:**
1. Bruker gjør endring i frontend
2. Frontend sender endring til API
3. API validerer endring
4. API analyserer konsekvenser
5. API lagrer i overlay-tabell
6. API oppretter change log entry
7. API trigger inkremetell build-links
8. API returnerer bekreftelse

**Revert-operasjoner:**
1. Bruker velger endring fra change log
2. API oppretter revert-change
3. API reverserer overlay-endringer
4. API oppdaterer change log
5. API trigger build-links

---

## 3. Database Design

### 3.1 Overlay-tabeller

#### `fotruteinfo_overlay`
Lagrer endringer i route metadata (rutenummer, rutenavn, etc.)

```sql
CREATE TABLE stiflyt.fotruteinfo_overlay (
    -- Primary key
    change_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Action type
    action VARCHAR(20) NOT NULL CHECK (action IN ('add', 'remove', 'modify', 'delete')),

    -- Segment reference
    segment_objid INTEGER NOT NULL,

    -- Original fotruteinfo reference (NULL for new entries)
    fotruteinfo_objid INTEGER,

    -- Route metadata (NULL for delete actions)
    rutenummer VARCHAR(50),
    rutenavn VARCHAR(255),
    vedlikeholdsansvarlig VARCHAR(255),
    rutetype VARCHAR(50),
    gradering VARCHAR(50),

    -- Original values (for revert)
    old_rutenummer VARCHAR(50),
    old_rutenavn VARCHAR(255),
    old_vedlikeholdsansvarlig VARCHAR(255),
    old_rutetype VARCHAR(50),
    old_gradering VARCHAR(50),

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100),
    applied BOOLEAN DEFAULT FALSE,
    parent_change_id UUID REFERENCES stiflyt.change_log(change_id),
    description TEXT,

    -- Indexes
    INDEX idx_fotruteinfo_overlay_segment (segment_objid),
    INDEX idx_fotruteinfo_overlay_rutenummer (rutenummer),
    INDEX idx_fotruteinfo_overlay_applied (applied),
    INDEX idx_fotruteinfo_overlay_created_at (created_at)
);
```

#### `fotrute_overlay`
Lagrer endringer i segment-geometri

```sql
CREATE TABLE stiflyt.fotrute_overlay (
    -- Primary key
    change_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Action type
    action VARCHAR(20) NOT NULL CHECK (action IN ('add', 'modify', 'delete')),

    -- Segment reference (NULL for new segments)
    segment_objid INTEGER,

    -- New segment ID (for new segments)
    new_segment_objid INTEGER,

    -- Geometry (NULL for delete actions)
    senterlinje GEOMETRY(LINESTRING, 25833),

    -- Original geometry (for revert)
    old_senterlinje GEOMETRY(LINESTRING, 25833),

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100),
    applied BOOLEAN DEFAULT FALSE,
    parent_change_id UUID REFERENCES stiflyt.change_log(change_id),
    description TEXT,

    -- Indexes
    INDEX idx_fotrute_overlay_segment (segment_objid),
    INDEX idx_fotrute_overlay_applied (applied),
    INDEX idx_fotrute_overlay_created_at (created_at),
    SPATIAL INDEX idx_fotrute_overlay_geom (senterlinje)
);
```

### 3.2 Change Log

#### `change_log`
Git-lignende log for alle endringer

```sql
CREATE TABLE stiflyt.change_log (
    -- Primary key
    change_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Parent changes (for merge scenarios)
    parent_change_ids UUID[],

    -- Change type
    change_type VARCHAR(50) NOT NULL CHECK (change_type IN ('commit', 'revert', 'merge')),

    -- Commit message
    message TEXT NOT NULL,

    -- Author
    author VARCHAR(100) NOT NULL,

    -- Timestamp
    timestamp TIMESTAMP DEFAULT NOW(),

    -- Affected entities
    affected_routes VARCHAR(50)[],
    affected_segments INTEGER[],

    -- Flexible metadata
    metadata JSONB,

    -- Indexes
    INDEX idx_change_log_type (change_type),
    INDEX idx_change_log_author (author),
    INDEX idx_change_log_timestamp (timestamp),
    INDEX idx_change_log_routes (affected_routes USING GIN),
    INDEX idx_change_log_segments (affected_segments USING GIN)
);
```

### 3.3 Merged Views

#### `fotruteinfo_merged`
View som kombinerer original + overlay

```sql
CREATE VIEW stiflyt.fotruteinfo_merged AS
WITH overlay_priority AS (
    -- Get latest overlay entry per segment_objid + rutenummer combination
    SELECT DISTINCT ON (segment_objid, rutenummer)
        change_id,
        segment_objid,
        fotruteinfo_objid,
        rutenummer,
        rutenavn,
        vedlikeholdsansvarlig,
        rutetype,
        gradering,
        action,
        created_at
    FROM stiflyt.fotruteinfo_overlay
    WHERE applied = FALSE
    ORDER BY segment_objid, rutenummer, created_at DESC
),
original_data AS (
    SELECT
        f.objid as segment_objid,
        fi.objid as fotruteinfo_objid,
        fi.rutenummer,
        fi.rutenavn,
        fi.vedlikeholdsansvarlig,
        fi.rutetype,
        fi.gradering,
        'original' as source
    FROM stiflyt.fotrute f
    JOIN stiflyt.fotruteinfo fi ON fi.fotrute_fk = f.objid
)
SELECT
    COALESCE(o.segment_objid, orig.segment_objid) as segment_objid,
    COALESCE(o.fotruteinfo_objid, orig.fotruteinfo_objid) as fotruteinfo_objid,
    COALESCE(o.rutenummer, orig.rutenummer) as rutenummer,
    COALESCE(o.rutenavn, orig.rutenavn) as rutenavn,
    COALESCE(o.vedlikeholdsansvarlig, orig.vedlikeholdsansvarlig) as vedlikeholdsansvarlig,
    COALESCE(o.rutetype, orig.rutetype) as rutetype,
    COALESCE(o.gradering, orig.gradering) as gradering,
    CASE
        WHEN o.action = 'delete' THEN FALSE
        WHEN o.action IN ('add', 'modify') THEN TRUE
        ELSE TRUE  -- Original exists
    END as is_active,
    COALESCE(o.change_id, NULL) as overlay_change_id
FROM original_data orig
FULL OUTER JOIN overlay_priority o ON o.segment_objid = orig.segment_objid
    AND o.rutenummer = orig.rutenummer
WHERE (o.action != 'delete' OR o.action IS NULL);
```

#### `fotrute_merged`
View som kombinerer original geometri + overlay

```sql
CREATE VIEW stiflyt.fotrute_merged AS
WITH overlay_priority AS (
    SELECT DISTINCT ON (COALESCE(segment_objid, new_segment_objid))
        change_id,
        COALESCE(segment_objid, new_segment_objid) as segment_objid,
        senterlinje,
        action,
        created_at
    FROM stiflyt.fotrute_overlay
    WHERE applied = FALSE
    ORDER BY COALESCE(segment_objid, new_segment_objid), created_at DESC
)
SELECT
    COALESCE(o.segment_objid, f.objid) as segment_objid,
    COALESCE(o.senterlinje, f.senterlinje) as senterlinje,
    CASE
        WHEN o.action = 'delete' THEN FALSE
        WHEN o.action IN ('add', 'modify') THEN TRUE
        ELSE TRUE
    END as is_active,
    COALESCE(o.change_id, NULL) as overlay_change_id
FROM stiflyt.fotrute f
FULL OUTER JOIN overlay_priority o ON o.segment_objid = f.objid
WHERE (o.action != 'delete' OR o.action IS NULL);
```

### 3.4 Hjelpetabeller

#### `change_impact_cache`
Cache for konsekvensanalyse (valgfritt, for ytelse)

```sql
CREATE TABLE stiflyt.change_impact_cache (
    change_id UUID PRIMARY KEY REFERENCES stiflyt.change_log(change_id),
    directly_affected_routes VARCHAR(50)[],
    indirectly_affected_routes VARCHAR(50)[],
    affected_segments INTEGER[],
    affected_links INTEGER[],
    distance_changes JSONB,
    topology_changes JSONB,
    calculated_at TIMESTAMP DEFAULT NOW(),
    INDEX idx_change_impact_cache_routes (directly_affected_routes USING GIN)
);
```

---

## 4. API Design

### 4.1 Endpoints

#### Change Management

**POST `/api/v1/changes`**
Registrer en ny endring

Request:
```json
{
  "message": "Fjernet bre50 fra segment 12345",
  "changes": [
    {
      "table": "fotruteinfo",
      "action": "remove_route",
      "segment_objid": 12345,
      "fotruteinfo_objid": 67890,
      "rutenummer": "bre50"
    }
  ],
  "analyze_impact": true,
  "rebuild_links": true
}
```

Response:
```json
{
  "change_id": "uuid",
  "message": "Fjernet bre50 fra segment 12345",
  "timestamp": "2024-01-15T14:30:00Z",
  "author": "user@example.com",
  "impact": {
    "directly_affected_routes": ["bre50"],
    "indirectly_affected_routes": ["bre60"],
    "affected_segments": [12345],
    "affected_links": [299, 300, 301]
  },
  "build_links_status": "completed",
  "validation_status": "ok"
}
```

**GET `/api/v1/changes`**
Hent change log

Query parameters:
- `route`: Filtrer på rute
- `segment`: Filtrer på segment
- `author`: Filtrer på forfatter
- `since`: Filtrer på dato
- `limit`: Antall resultater
- `offset`: Paginering

Response:
```json
{
  "changes": [
    {
      "change_id": "uuid",
      "change_type": "commit",
      "message": "Fjernet bre50 fra segment 12345",
      "author": "user@example.com",
      "timestamp": "2024-01-15T14:30:00Z",
      "affected_routes": ["bre50", "bre60"],
      "affected_segments": [12345]
    }
  ],
  "total": 100,
  "limit": 20,
  "offset": 0
}
```

**GET `/api/v1/changes/{change_id}`**
Hent detaljer for en endring

Response:
```json
{
  "change_id": "uuid",
  "change_type": "commit",
  "message": "Fjernet bre50 fra segment 12345",
  "author": "user@example.com",
  "timestamp": "2024-01-15T14:30:00Z",
  "parent_change_ids": [],
  "affected_routes": ["bre50", "bre60"],
  "affected_segments": [12345],
  "changes": [
    {
      "table": "fotruteinfo",
      "action": "remove_route",
      "segment_objid": 12345,
      "fotruteinfo_objid": 67890,
      "rutenummer": "bre50",
      "old_value": {
        "rutenummer": "bre50",
        "rutenavn": "Breivasshytta",
        "vedlikeholdsansvarlig": "DNT Oslo"
      },
      "new_value": null
    }
  ],
  "impact": {
    "directly_affected_routes": ["bre50"],
    "indirectly_affected_routes": ["bre60"],
    "affected_segments": [12345],
    "affected_links": [299, 300, 301]
  }
}
```

**POST `/api/v1/changes/{change_id}/revert`**
Revert en endring

Request:
```json
{
  "message": "Revert: Fjernet bre50 fra segment 12345",
  "reason": "Feil segment valgt"
}
```

Response:
```json
{
  "revert_change_id": "uuid",
  "original_change_id": "uuid",
  "message": "Revert: Fjernet bre50 fra segment 12345",
  "timestamp": "2024-01-15T15:00:00Z"
}
```

**GET `/api/v1/changes/{change_id}/diff`**
Hent diff for en endring

Response:
```json
{
  "change_id": "uuid",
  "diff": {
    "fotruteinfo": [
      {
        "segment_objid": 12345,
        "rutenummer": "bre50",
        "action": "removed",
        "old_value": {
          "rutenummer": "bre50",
          "rutenavn": "Breivasshytta"
        }
      }
    ]
  }
}
```

#### Impact Analysis

**POST `/api/v1/changes/analyze-impact`**
Analyser konsekvenser før commit

Request:
```json
{
  "changes": [
    {
      "table": "fotruteinfo",
      "action": "remove_route",
      "segment_objid": 12345,
      "fotruteinfo_objid": 67890,
      "rutenummer": "bre50"
    }
  ]
}
```

Response:
```json
{
  "impact": {
    "directly_affected_routes": ["bre50"],
    "indirectly_affected_routes": ["bre60"],
    "affected_segments": [12345],
    "affected_links": [299, 300, 301],
    "distance_changes": [
      {
        "route": "bre50",
        "old_length": 15000.5,
        "new_length": 12000.3,
        "difference": -3000.2
      }
    ],
    "topology_changes": [
      {
        "link_id": 299,
        "change": "route_removed",
        "affected_routes": ["bre50"]
      }
    ],
    "validation_required": true
  },
  "warnings": [
    "Route bre50 will have no segments after this change"
  ]
}
```

#### Report Generation

**POST `/api/v1/reports/generate`**
Generer rapport for kartverket

Request:
```json
{
  "change_ids": ["uuid1", "uuid2"],
  "format": "json",  // json | csv | sql | markdown
  "include_metadata": true
}
```

Response:
```json
{
  "report_id": "uuid",
  "format": "json",
  "generated_at": "2024-01-15T16:00:00Z",
  "content": "...",
  "download_url": "/api/v1/reports/{report_id}/download"
}
```

**GET `/api/v1/reports/{report_id}/download`**
Last ned generert rapport

#### Build Links

**POST `/api/v1/routes/{rutenummer}/rebuild-links`**
Rebuild links for en spesifikk rute

Response:
```json
{
  "rutenummer": "bre50",
  "status": "completed",
  "links_rebuilt": 15,
  "duration_seconds": 2.5
}
```

**POST `/api/v1/changes/{change_id}/rebuild-links`**
Rebuild links for alle berørte ruter i en endring

Response:
```json
{
  "change_id": "uuid",
  "status": "completed",
  "routes_rebuilt": ["bre50", "bre60"],
  "links_rebuilt": 25,
  "duration_seconds": 5.2
}
```

---

## 5. Frontend Design

### 5.1 UI-komponenter

#### Change Log View
- Liste over alle endringer (git log-lignende)
- Filtrer på rute, segment, dato, forfatter
- Vis diff for hver endring
- Revert-knapp per endring
- Batch-operasjoner (revert flere, generer rapport)

#### Change Creation
- "Fjern rutenummer"-knapp i segmentdetaljer
- Bekreftelsesdialog med preview
- Commit-melding (valgfritt)
- Vis konsekvenser før commit
- Progress-indikator for build-links

#### Diff View
- Side-by-side visning (før/etter)
- Fargekodet (rød=fjernet, grønn=lagt til)
- Vis berørte ruter/segmenter/linker
- GeoJSON diff (visuelle endringer på kart)

#### Report Generation
- "Generer diff-rapport"-knapp
- Velg format (JSON/CSV/SQL/Markdown)
- Eksporter eller vis i browser
- Formatert for kartverket

### 5.2 Workflow

**Normal endring:**
1. Bruker ser segment i frontend
2. Klikker "Fjern rutenummer"
3. System viser konsekvensanalyse
4. Bruker bekrefter og legger til commit-melding
5. System oppretter change log entry
6. System kjører inkremetell build-links
7. System validerer endringer
8. Endringer vises umiddelbart (via overlay)

**Revert:**
1. Bruker velger endring fra change log
2. System viser diff og konsekvenser
3. Bruker bekrefter revert
4. System oppretter revert change
5. System kjører build-links
6. Endringer reverseres

**Rapport-generering:**
1. Bruker velger endringer fra change log
2. System genererer rapport
3. Bruker eksporterer eller sender til kartverket

---

## 6. Business Logic

### 6.1 Overlay Service

**Funksjoner:**
- `register_change()`: Registrer endring i overlay
- `get_merged_data()`: Hent data fra merged view
- `apply_overlay()`: Merge overlay inn i hovedtabell (ved nedlasting)
- `clear_overlay()`: Slett overlay (start på nytt)

### 6.2 Change Log Service

**Funksjoner:**
- `commit_change()`: Opprett ny change log entry
- `revert_change()`: Revert en endring
- `get_change_history()`: Hent historikk
- `get_diff()`: Vis diff mellom endringer
- `merge_changes()`: Merge flere endringer

### 6.3 Impact Analysis Service

**Funksjoner:**
- `analyze_change_impact()`: Analyser konsekvenser
- `get_affected_routes()`: Hent berørte ruter
- `get_affected_segments()`: Hent berørte segmenter
- `get_affected_links()`: Hent berørte linker
- `calculate_distance_changes()`: Beregn distanseendringer

### 6.4 Report Generator Service

**Funksjoner:**
- `generate_kartverket_report()`: Generer rapport for kartverket
- `generate_sql_script()`: Generer SQL-script
- `generate_markdown_report()`: Generer Markdown-rapport
- `generate_csv_report()`: Generer CSV-rapport

### 6.5 Build Links Service

**Funksjoner:**
- `rebuild_links_for_route()`: Rebuild links for en rute
- `rebuild_links_for_changes()`: Rebuild links for endringer
- `incremental_rebuild()`: Inkremetell rebuild
- `full_rebuild()`: Full rebuild

---

## 7. Validering

### 7.1 Eksisterende Validators

Systemet har allerede følgende validators:
- `RouteGeometryValidator`: Validerer route-geometri
- `LinkConnectivityValidator`: Validerer link-tilkoblinger
- `SegmentGapValidator`: Validerer gaps mellom segmenter
- `MetadataConsistencyValidator`: Validerer metadata-konsistens
- `DuplicateMetadataValidator`: Detekterer duplikater
- `MissingFieldsValidator`: Detekterer manglende felt

### 7.2 Nye Validators

**OverlayValidator:**
- Validerer at overlay-endringer er konsistente
- Sjekker at segmenter/ruter eksisterer
- Validerer at revert-operasjoner er gyldige

**ChangeImpactValidator:**
- Validerer at endringer ikke bryter constraints
- Sjekker at berørte ruter fortsatt er gyldige
- Validerer at link-topologi er konsistent

---

## 8. Task Liste

### Fase 1: Grunnleggende Overlay (2-3 uker)

#### Database
- [ ] Opprett `fotruteinfo_overlay` tabell
- [ ] Opprett `fotrute_overlay` tabell
- [ ] Opprett `change_log` tabell
- [ ] Opprett `fotruteinfo_merged` view
- [ ] Opprett `fotrute_merged` view
- [ ] Opprett indexes
- [ ] Skriv migrasjonsscript

#### Backend - Overlay Service
- [ ] Implementer `OverlayService` klasse
- [ ] Implementer `register_change()` metode
- [ ] Implementer `get_merged_data()` metode
- [ ] Implementer `clear_overlay()` metode
- [ ] Skriv unit tests

#### Backend - Change Log Service
- [ ] Implementer `ChangeLogService` klasse
- [ ] Implementer `commit_change()` metode
- [ ] Implementer `get_change_history()` metode
- [ ] Skriv unit tests

#### API Endpoints
- [ ] Implementer `POST /api/v1/changes`
- [ ] Implementer `GET /api/v1/changes`
- [ ] Implementer `GET /api/v1/changes/{change_id}`
- [ ] Legg til API-dokumentasjon
- [ ] Skriv integration tests

#### Frontend - Grunnleggende UI
- [ ] Legg til "Fjern rutenummer"-knapp i segmentdetaljer
- [ ] Implementer bekreftelsesdialog
- [ ] Implementer commit-melding input
- [ ] Vis bekreftelse etter endring
- [ ] Oppdater segmentdetaljer etter endring

### Fase 2: Change Log og Revert (2 uker)

#### Backend - Revert Funksjonalitet
- [ ] Implementer `revert_change()` metode
- [ ] Implementer diff-generering
- [ ] Skriv unit tests

#### API Endpoints
- [ ] Implementer `POST /api/v1/changes/{change_id}/revert`
- [ ] Implementer `GET /api/v1/changes/{change_id}/diff`
- [ ] Legg til API-dokumentasjon

#### Frontend - Change Log View
- [ ] Opprett change log-side/komponent
- [ ] Implementer liste over endringer
- [ ] Implementer filtrering
- [ ] Implementer diff-visning
- [ ] Implementer revert-knapp
- [ ] Legg til navigasjon til change log

### Fase 3: Konsekvensanalyse (2 uker)

#### Backend - Impact Analysis Service
- [ ] Implementer `ImpactAnalysisService` klasse
- [ ] Implementer `analyze_change_impact()` metode
- [ ] Implementer `get_affected_routes()` metode
- [ ] Implementer `get_affected_segments()` metode
- [ ] Implementer `get_affected_links()` metode
- [ ] Implementer `calculate_distance_changes()` metode
- [ ] Skriv unit tests

#### API Endpoints
- [ ] Implementer `POST /api/v1/changes/analyze-impact`
- [ ] Legg til impact i `POST /api/v1/changes` response
- [ ] Legg til API-dokumentasjon

#### Frontend - Impact Visning
- [ ] Vis konsekvenser før commit
- [ ] Vis berørte ruter/segmenter/linker
- [ ] Vis distanseendringer
- [ ] Vis advarsler

### Fase 4: Inkremetell Build-Links (2-3 uker)

#### Backend - Build Links Service
- [ ] Implementer `BuildLinksService` klasse
- [ ] Implementer `rebuild_links_for_route()` metode
- [ ] Implementer `rebuild_links_for_changes()` metode
- [ ] Implementer `incremental_rebuild()` metode
- [ ] Integrer med change log
- [ ] Skriv unit tests

#### API Endpoints
- [ ] Implementer `POST /api/v1/routes/{rutenummer}/rebuild-links`
- [ ] Implementer `POST /api/v1/changes/{change_id}/rebuild-links`
- [ ] Legg til API-dokumentasjon

#### Frontend - Build Links Status
- [ ] Vis build-links status i change log
- [ ] Vis progress-indikator
- [ ] Vis feilmeldinger hvis build-links feiler

### Fase 5: Diff/Rapport-generering (2 uker)

#### Backend - Report Generator Service
- [ ] Implementer `ReportGeneratorService` klasse
- [ ] Implementer `generate_kartverket_report()` metode
- [ ] Implementer `generate_sql_script()` metode
- [ ] Implementer `generate_markdown_report()` metode
- [ ] Implementer `generate_csv_report()` metode
- [ ] Skriv unit tests

#### API Endpoints
- [ ] Implementer `POST /api/v1/reports/generate`
- [ ] Implementer `GET /api/v1/reports/{report_id}/download`
- [ ] Legg til API-dokumentasjon

#### Frontend - Rapport-generering
- [ ] Legg til "Generer rapport"-knapp i change log
- [ ] Implementer format-valg
- [ ] Implementer eksport-funksjonalitet
- [ ] Vis preview av rapport

### Fase 6: Merge-strategi (2 uker)

#### Backend - Merge Service
- [ ] Implementer `MergeService` klasse
- [ ] Implementer pre-merge validering
- [ ] Implementer auto-merge logikk
- [ ] Implementer konflikthåndtering
- [ ] Implementer post-merge opprydding
- [ ] Skriv unit tests

#### CLI Tools
- [ ] Implementer `merge_overlay.py` script
- [ ] Implementer konflikthåndtering i script
- [ ] Skriv dokumentasjon

### Fase 7: Testing og Dokumentasjon (1-2 uker)

#### Testing
- [ ] Skriv integration tests for hele workflow
- [ ] Skriv end-to-end tests
- [ ] Performance testing
- [ ] Load testing

#### Dokumentasjon
- [ ] Oppdater README
- [ ] Skriv brukerguide
- [ ] Skriv API-dokumentasjon
- [ ] Skriv database-dokumentasjon
- [ ] Skriv deploy-guide

### Fase 8: Polish og Optimering (1 uke)

#### Optimering
- [ ] Optimaliser database-queries
- [ ] Legg til caching hvor nødvendig
- [ ] Optimaliser build-links ytelse

#### UI/UX
- [ ] Forbedre feilmeldinger
- [ ] Legg til loading states
- [ ] Forbedre responsivitet
- [ ] Legg til keyboard shortcuts

---

## 9. Tekniske Detaljer

### 9.1 Teknologier

- **Backend**: Python 3.9+, FastAPI, psycopg3
- **Database**: PostgreSQL 12+, PostGIS 3.0+
- **Frontend**: HTML5, JavaScript (ES6+), Leaflet.js
- **Testing**: pytest, pytest-asyncio
- **Documentation**: Markdown, OpenAPI/Swagger

### 9.2 Ytelseskrav

- API-respons: < 500ms for de fleste endpoints
- Build-links: < 30s for en enkelt rute
- Change log query: < 200ms
- Impact analysis: < 2s

### 9.3 Sikkerhet

- Validering av alle inputs
- SQL injection prevention (parameterized queries)
- Authorization (fremtidig)
- Audit trail (change log)

### 9.4 Feilhåndtering

- Graceful degradation
- Tydelige feilmeldinger
- Rollback ved feil
- Logging av alle feil

---

## 10. Fremtidige Utvidelser

### 10.1 Mulige Utvidelser

- **Batch-operasjoner**: Gjøre flere endringer samtidig
- **Undo/Redo**: Mer avansert historikk
- **Branches**: Git-lignende branches for endringer
- **Merge requests**: Review-prosess før merge
- **Automated testing**: Automatisk validering ved endringer
- **Notifications**: Varsle ved endringer
- **Export formats**: Flere export-formater
- **Import**: Importer endringer fra kartverket

### 10.2 Integrasjoner

- **Kartverket API**: Direkte integrasjon med kartverket
- **Git**: Integrer med Git for versjonskontroll
- **CI/CD**: Automatisk testing og deploy
- **Monitoring**: Overvåking av systemet

---

## 11. Vedlikehold og Support

### 11.1 Vedlikehold

- Regelmessig opprydding av gamle endringer
- Optimalisering av database-queries
- Oppdatering av avhengigheter
- Sikkerhetsoppdateringer

### 11.2 Support

- Dokumentasjon
- Feilrapportering
- Brukerstøtte
- Training

---

## 12. Konklusjon

Dette dokumentet beskriver en komplett løsning for rutevalidering og repair med overlay-lag. Løsningen gir:

- **Fleksibilitet**: Lokale endringer uten å modifisere originale data
- **Sporbarhet**: Git-lignende log for alle endringer
- **Kontroll**: Revert og merge-funksjonalitet
- **Rapportering**: Diff og rapporter for kartverket
- **Ytelse**: Inkremetell build-links for rask oppdatering

Implementeringen er delt inn i 8 faser som kan utføres inkrementelt, med hver fase som leverer verdi.

---

## Vedlegg

### A. Database Schema Diagram

```
┌─────────────────────┐
│   fotrute           │
│   (original)        │
└──────────┬──────────┘
           │
           │ fotrute_fk
           │
┌──────────▼──────────┐
│   fotruteinfo       │
│   (original)        │
└─────────────────────┘

┌─────────────────────┐
│ fotruteinfo_overlay │
│   (changes)         │
└─────────────────────┘

┌─────────────────────┐
│   change_log        │
│   (history)         │
└─────────────────────┘
```

### B. API Request/Response Eksempler

Se seksjon 4 for detaljerte eksempler.

### C. Frontend Mockups

Mockups kan legges til senere.

---

**Dokument slutt**
