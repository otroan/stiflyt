# Stiflyt

## Grunneiere

### Problem

Når det skal være dugnad eller endringer på ei vandrerute så skal grunneierne varsles.

Dagens arbeidsflyt:
 - Gå inn på norgeskart.no og klikke manuelt langs hele ruta for å finne matrikkelenhetene (kommune, gards og bruksnummer).
 - Gå inn på seeiendom.kartverket.no for å finne navnet til grunneierene.
 - Gule sider/Google/Chatgpt for å finne kontaktinformasjon.

Dette er tungvint og tidskrevende.

### Løsning

En kartløsning (stiflyt.dnt.no) hvor våre ruter vises eller kan søkes frem. Brukeren klikker på ruta og får en liste med alle grunneierne.
Lista vil i første omgang bestå av matrikkelenhet, avstand fra start, navn på grunneier. Denne listen kan så lastes ned i Excel eller CSV format.
Verktøyet skal også tillate at man kan klikke på steder i kartet og få opp eierinformasjonen direkte. Praktisk for f.eks bruarbeid.

I backend vil løsningen bestå av en PostGIS database med daglig nedlastning av turrutebasen, teiger og stedsnavn.
Det legges et mellomlag oppå turrutebasen. Her preprosesseres rutene og det gjøres oppslag i teigtabellen for å finne matrikkelenhetene.

Adgang til matrikkelenhet er åpent, mens adgang til selve matrikkelen er mer kontrollert.
Sannsynligvis må vi ha en innloggingsløsning slik at grunneier navn og kontaktinformasjon kun gies til innloggede brukere.
Kartverket har et API (matrikkel APIet) for å slå opp eier informasjon fra matrikkelenhet.

Første fase så kommer vi kun til å vise eiernavn. Men når løsningen er oppe så kan vi ta opp igjen diskusjonen med kartverket om å få tilgang til kontaktinformasjon også.

## Feil i turrutebasen

### Problem

Rutene i Turrutebasen har mye feil. Det synes tydligst på ut.no hvor man ofte får opp "merket fotrute" i stedet for en lenke til turbeskrivelsen.
Når man skal bruke turrutebasen til å automatisk lage skiltoversikt eller til ruteplanlegger så må rutene være korrekte.

- Ruter henger ikke sammen
- Feil i metadata, f.eks mangler rutenummer
- Løse ender

Kartverket har et en webside hvor man kan manuelt legge inn endringer og så kommer noen i kartverket og retter på det i løpet av noen uker eller måneder.

### Løsning

Automatisk detektere ruter med feil. Diskutere med kartverket om mer effektive måter å rapportere "feil i bulk".
Lage et mellomlag over turrutebasen hvor enten manuelt eller automatisk fiksede ruter gjøres tilgjengelig for resten av verktøyet.

Også legge til muligheter for å redigere rutene direkte i verktøyet? Lære fra opplastede GPXer eller fra traktor og sti databasen?

## Rutestatus, Dagbok for rutene, Issue tracker

### Problem

Idag ikke OKene noe felles måte å synliggjøre "status" på rutene. F.eks har vi et excel regneark, mens andre sikkert har andre løsninger.
Dugnadsrapporter, OK rapporter lagres på papir og er ikke tilgjengelige åpent. Det gjør det vanskelig å vite hva som har vært gjort tidligere på ruta,
det gjør det vanskeligere med "handover" til nye OKer og det gjør det vanskeligere å lære av tidligere feil.

### Løsning

Dugnader og inspeksjoner rapporteres inn i "systemet". Visualisering slik som skisporet slik at man kan se med farger hvilke ruter som er i god eller dårlig stand, nylig hatt dugnad eller det har vært gått inspeksjon på.
Hver rute har en "rutebok" slik som en hyttbok hvor alt arbeid noteres.
I tillegg har man en "issue tracker" slik at når man får klager eller meldinger på en rute, legges de inn i issue trackeren. Denne kan følges med på av OKen, ruteinspektøren og andre tillitsvalgte.

## Skilt

### Problem

Idag finnes det en skiltdatabase som brukes mye for skilt i marka og litt for skilt i fjellet. Skiltdatabasen er noe tung å bruke, og de fleste OKer håndterer skilt manuelt.
Nå når skilt må bestilles med fast pil og kilometeravstand så er det en mer involvert jobb.

### Løsning

Alle ruter har skilt ved endepunktene og ved kryss. Skiltsteder og skilt kan derfor genereres automatisk. Selvsagt vil det være noen unntak. Man må også manuelt legge til skiltretning og status på skiltet. Eventuelt sjekke kvalitet med AI.

## Kartlag for egne GPX filer, bilder, kulturminner

Laste opp sine egne GPX filer for å verifisere at rutene i turrutebasen matcher de faktiske rutene. Særlig nyttig ved omlegginger.
Kunne laste opp sine egne bilder og gjøre disse tilgjengelig for alle brukerne av verktøyet. Praktisk for planlegging av dugnader etc.
Gi advarsler ved dugnad om områder hvor de ikke må ta stein etc.

## Prosjektplan

Første fase er å få på plass løsningen for å vise grunneiere.
Når det er på plass kan vi diskutere videre prioriteringer.

## DNT HQ - UT samarbeid

UT burde ha åpne APIer for:
- "rettede" ruter med rutebeskrivelser.
- hytter med åpningstider og annen metadata
- bruer og sommerbru åpningstider
- kvisting og kvistestatus


