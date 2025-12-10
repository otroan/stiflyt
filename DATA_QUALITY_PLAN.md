# Data Quality Plan for Route Processing

## Problem
Datagrunnlaget har flere problemer:
- SQL-feil ved lengdeberegning (generate_series i SUM)
- Segmenter som ikke kobles sammen
- Overlappende segmenter
- Feilaktige lengder (Web Mercator vs geography)
- Manglende metadata
- Løse ender i ruter

## Foreslått Løsning: Preprosessering og Validering

### 1. Preprosesseringspipeline

#### 1.1 Valideringsmodul (`scripts/validate_routes.py`)
En separat script som:
- Går gjennom alle rutene i databasen
- Validerer hver rute for:
  - Kan kombineres til en gyldig geometri
  - Kan beregne lengde korrekt
  - Segmenter kobles sammen
  - Ingen overlapp
  - Metadata er komplett
- Kategoriserer feil:
  - **KRITISK**: Ruten kan ikke prosesseres (SQL-feil, ugyldig geometri)
  - **ADVARSEL**: Ruten kan prosesseres men har problemer (løse ender, overlapp)
  - **INFO**: Ruten er OK men har mindre avvik (metadata mangler)

#### 1.2 Feilrapportering
- Genererer en strukturert rapport (JSON/CSV/HTML)
- Inkluderer:
  - Rutenummer
  - Feilkategori
  - Feilbeskrivelse
  - SQL-feilmelding (hvis relevant)
  - Antall segmenter
  - Geometritype
  - Forslag til løsning

### 2. Database-struktur for validering

#### 2.1 Valideringstabell (valgfritt)
```sql
CREATE TABLE route_validation (
    rutenummer VARCHAR(50) PRIMARY KEY,
    validation_status VARCHAR(20), -- 'OK', 'WARNING', 'ERROR'
    validation_date TIMESTAMP,
    error_category VARCHAR(50),
    error_message TEXT,
    error_details JSONB,
    segment_count INTEGER,
    geometry_type VARCHAR(50),
    can_process BOOLEAN,
    notes TEXT
);
```

#### 2.2 Flagg i eksisterende tabell (alternativ)
Legg til kolonner i `fotruteinfo`:
- `validation_status`
- `last_validated`
- `validation_errors`

### 3. Valideringskriterier

#### 3.1 Geometri-validering
- [ ] Kan kombineres med `ST_LineMerge`
- [ ] Resulterer i gyldig geometri (`ST_IsValid`)
- [ ] Kan beregne lengde uten SQL-feil
- [ ] Segmenter er koblet sammen (avstand mellom endepunkter < terskel)

#### 3.2 Data-kvalitet
- [ ] Ingen overlappende segmenter
- [ ] Segmentlengder er realistiske (ikke 0, ikke ekstremt lange)
- [ ] Totallengde stemmer med sum av segmenter (±toleranse)
- [ ] Metadata er komplett (rutenavn, vedlikeholdsansvarlig)

#### 3.3 Matrikkelenhet-validering
- [ ] Ruten har overlapp med teig-data
- [ ] Dekningsgrad er realistisk (ikke 0%, ikke >100%)
- [ ] Offset-beregninger fungerer

### 4. Implementeringsforslag

#### 4.1 Valideringsscript (`scripts/validate_routes.py`)
```python
"""
Validerer alle rutene i databasen og genererer en feilrapport.
Kan kjøres periodisk eller ved oppdatering av data.
"""

def validate_all_routes():
    """Validerer alle rutene og genererer rapport."""
    routes = get_all_routes()
    results = []

    for route in routes:
        validation = validate_route(route['rutenummer'])
        results.append(validation)

    generate_report(results)

def validate_route(rutenummer):
    """Validerer en enkelt rute."""
    errors = []
    warnings = []

    # Test hver operasjon
    try:
        segments = get_route_segments(rutenummer)
        geometry = combine_route_geometry(segments)
        length = get_route_length(geometry)  # Kan feile her
        # ... flere tester
    except Exception as e:
        errors.append({
            'category': 'SQL_ERROR',
            'message': str(e),
            'operation': 'get_route_length'
        })

    return {
        'rutenummer': rutenummer,
        'status': 'ERROR' if errors else 'WARNING' if warnings else 'OK',
        'errors': errors,
        'warnings': warnings
    }
```

#### 4.2 API-endepunkt for validering (valgfritt)
```python
@router.get("/routes/{rutenummer}/validate")
async def validate_route_endpoint(rutenummer: str):
    """Validerer en rute og returnerer status."""
    validation = validate_route(rutenummer)
    return validation
```

### 5. Rapportering

#### 5.1 Rapportformater
- **JSON**: For programmatisk bruk
- **CSV**: For Excel/analyse
- **HTML**: For visuell gjennomgang
- **Markdown**: For dokumentasjon

#### 5.2 Rapportinnhold
```json
{
  "validation_date": "2024-01-15T10:00:00Z",
  "total_routes": 150,
  "ok_routes": 120,
  "warning_routes": 20,
  "error_routes": 10,
  "routes": [
    {
      "rutenummer": "bre5",
      "status": "ERROR",
      "errors": [
        {
          "category": "SQL_ERROR",
          "message": "aggregate function calls cannot contain set-returning function calls",
          "operation": "get_route_length",
          "suggestion": "Bruk LATERAL JOIN eller loop i stedet for generate_series i SUM"
        }
      ],
      "can_process": false
    }
  ]
}
```

### 6. Workflow

#### 6.1 Periodisk validering
- Kjør validering etter hver dataoppdatering
- Kjør månedlig validering av alle rutene
- Send rapport til kartverket

#### 6.2 Feilhåndtering i produksjon
- API-et sjekker valideringstabell før prosessering
- Returnerer feilmelding hvis rute har kritiske feil
- Logger alle feil for oppfølging

### 7. Integrasjon med eksisterende system

#### 7.1 Graceful degradation
- Hvis rute har kritiske feil: returner feilmelding
- Hvis rute har advarsler: returner data med advarsel i metadata
- Logg alle feil for oppfølging

#### 7.2 Caching av valideringsresultater
- Cache valideringsresultater i minnet eller database
- Oppdater cache når data endres
- Reduserer belastning på database

### 8. Neste steg

1. **Implementer valideringsscript** (`scripts/validate_routes.py`)
2. **Kjør validering på alle rutene** og generer første rapport
3. **Send rapport til kartverket** med konkrete feil
4. **Implementer valideringstabell** (valgfritt)
5. **Oppdater API** til å sjekke validering før prosessering
6. **Automatiser validering** ved dataoppdateringer

### 9. Eksempel på valideringsrapport

```markdown
# Route Validation Report
Generated: 2024-01-15 10:00:00

## Summary
- Total routes: 150
- OK: 120 (80%)
- Warnings: 20 (13%)
- Errors: 10 (7%)

## Critical Errors (Cannot Process)

### bre5
- **Error**: SQL error in get_route_length
- **Message**: aggregate function calls cannot contain set-returning function calls
- **Suggestion**: Fix MultiLineString length calculation query
- **Impact**: Route cannot be displayed

## Warnings (Can Process but Issues Found)

### bre10
- **Warning**: Route length mismatch (42.69 km vs 20.23 km)
- **Cause**: Web Mercator distortion in original calculation
- **Status**: Fixed in code, but data should be validated

## Recommendations

1. Fix SQL query for MultiLineString length calculation
2. Validate all route geometries for validity
3. Check for disconnected segments
4. Verify metadata completeness
```

