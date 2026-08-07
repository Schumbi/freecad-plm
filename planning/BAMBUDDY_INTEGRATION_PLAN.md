# Bambuddy-Integration

## Ziel

FreeCAD-PLM soll die tatsächlich gedruckte `gcode.3mf` und den zugehörigen
Drucklauf automatisch aus Bambuddy übernehmen können. Die Zuordnung zu einer
PLM-Revision muss nachvollziehbar sein. Reine Dateinamensheuristiken dürfen
keine automatische, möglicherweise falsche Verknüpfung erzeugen.

## Verifizierter API-Vertrag

Bambuddy stellt eine HTTP-API unter `/api/v1` bereit. Für den ersten Ausbau
werden nur lesende Aufrufe benötigt:

- `GET /api/v1/archives` listet Archive.
- `GET /api/v1/archives/{id}` liefert die Details eines Archivs.
- `GET /api/v1/archives/{id}/3mf` lädt die archivierte 3MF-Datei.
- Die Authentifizierung erfolgt über den Header `X-API-Key`.
- Für diese Aufrufe genügt ein API-Key mit der Bambuddy-Berechtigung
  `Read Status`.

## Sicherheit und Konfiguration

- URL und API-Key sind Serverkonfiguration und werden nicht im FreeCAD-Addon
  gespeichert.
- Der API-Key liegt ausschließlich in der Laufzeitumgebung und wird weder in
  der Datenbank noch im HTML ausgegeben.
- Es wird ein eigener Key mit minimaler Berechtigung `Read Status` verwendet.
- Der Client prüft die URL, verwendet die normale TLS-Zertifikatsprüfung und
  begrenzt Timeout sowie JSON-Antwortgröße.

Konfiguration:

```env
BAMBUDDY_URL=http://bambuddy.example.local:8000
BAMBUDDY_API_KEY=bb_...
BAMBUDDY_TIMEOUT_SECONDS=10
```

Unter `Verwaltung -> Integrationen` kann ein Admin die wirksame Konfiguration
sehen und mit einem rein lesenden Aufruf testen. Der API-Key wird dabei nicht
angezeigt.

## Umsetzungsschritte

### Phase A: Verbindung

- [x] Bambuddy-Client mit URL-Prüfung, API-Key-Header und Fehlerklassen.
- [x] Umgebungsvariablen an Web und Worker durchreichen.
- [x] Admin-Seite mit Konfigurationsstatus und Verbindungstest.
- [x] Client und View automatisiert testen.

### Phase B: Archiveingang

- [ ] Archive inkrementell und idempotent auflisten.
- [ ] Externe Bambuddy-ID und Synchronisationscursor dauerhaft speichern.
- [ ] Noch nicht zugeordnete Archive in einem Eingang anzeigen.
- [ ] Archivdetails anzeigen und manuelle Zuordnung zu Revision und
  Fertigungsdatei ermöglichen.
- [ ] Für eine spätere Automatik stabile PLM-Kennungen aus den Archivmetadaten
  untersuchen; bei Mehrdeutigkeit immer manuelle Zuordnung verlangen.

### Phase C: Unveränderliche Druckdatei

- [ ] Zugeordnete `gcode.3mf` über den Archiv-Endpunkt herunterladen.
- [ ] Dateityp und Größenlimits vor dem Speichern prüfen.
- [ ] SHA-256 bilden und denselben Download idempotent behandeln.
- [ ] Datei als unveränderliche `ManufacturingFile` an der richtigen Revision
  speichern und den Import auditieren.

### Phase D: Fertigungslauf

- [ ] Bambuddy-Status, Zeiten, Maschine, Material und weitere verfügbare
  Metadaten in `ManufacturingRun` übernehmen.
- [ ] Aktualisierungen quellenbezogen und idempotent verarbeiten.
- [ ] Bambuddy-Notizen oder Tags nicht still über vorhandene PLM-Notizen
  schreiben.

### Phase E: Sichere Automatisierung

- [ ] Worker-Job mit Cursor, Retry und nachvollziehbaren Fehlermeldungen.
- [ ] Nur eindeutig identifizierte Archive automatisch zuordnen.
- [ ] Unklare Fälle im Archiveingang belassen.
- [ ] Synchronisationszustand und letzten erfolgreichen Lauf in der Web-UI
  sichtbar machen.

## Nächster Schritt

Mit einem nur lesenden Bambuddy-Key wird der Verbindungstest gegen die echte
Instanz durchgeführt. Danach folgt Phase B zunächst ausschließlich als
Metadatenimport ohne automatischen 3MF-Download oder automatische Zuordnung.
