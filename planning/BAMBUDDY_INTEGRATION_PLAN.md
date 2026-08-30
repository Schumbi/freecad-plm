# Bambuddy-Integration

## Ziel

FreeCAD-PLM soll die tatsächlich gedruckte `gcode.3mf` und den zugehörigen
Drucklauf automatisch aus Bambuddy übernehmen können. Die Zuordnung zu einer
PLM-Revision muss nachvollziehbar sein. Reine Dateinamensheuristiken dürfen
keine automatische, möglicherweise falsche Verknüpfung erzeugen.

## Verifizierter API-Vertrag

Bambuddy stellt eine HTTP-API unter `/api/v1` bereit. Der aktuelle Ausbau
verwendet diese Aufrufe:

- `GET /api/v1/archives/` listet Archive. Bambuddy-Versionen liefern dabei
  entweder eine direkte JSON-Liste oder ein Objekt mit `archives` und `total`;
  der Client unterstützt beide Formate.
- `GET /api/v1/archives/{id}` liefert die Details eines Archivs.
- `GET /api/v1/archives/{id}/download` lädt in der produktiv eingesetzten
  Bambuddy-Version die archivierte 3MF-Datei.
- `POST /api/v1/archives/{id}/source` hängt die ursprüngliche Slicer-3MF als
  Source-Datei an ein konkretes Archiv. Dieser Weg vermeidet die unscharfe
  Namenssuche von `/api/v1/archives/upload-source`.
- `PATCH /api/v1/archives/{id}` setzt unter anderem `external_url`. Der
  PLM-Worker verwendet diesen Endpunkt für einen Link auf die konkrete
  Revisionskarte.
- Die Authentifizierung erfolgt über den Header `X-API-Key`.
- Für lesende Aufrufe genügt `Read Status`; Source-Upload und Revisionslink
  benötigen zusätzlich `Manage Archives` und effektiv `archives:update_all`.

## Sicherheit und Konfiguration

- URL und API-Key sind Serverkonfiguration und werden nicht im FreeCAD-Addon
  gespeichert.
- Der API-Key liegt ausschließlich in der Laufzeitumgebung und wird weder in
  der Datenbank noch im HTML ausgegeben.
- Es wird ein eigener Key mit minimalen Berechtigungen verwendet. Für den
  Source-Sync sind dies `Read Status` und `Manage Archives`.
- Der Client prüft die URL, verwendet die normale TLS-Zertifikatsprüfung und
  begrenzt Timeout sowie JSON-Antwortgröße.

Konfiguration:

```env
BAMBUDDY_URL=http://bambuddy.example.local:8000
BAMBUDDY_API_KEY=bb_...
BAMBUDDY_TIMEOUT_SECONDS=10
BAMBUDDY_SOURCE_SYNC_ENABLED=1
BAMBUDDY_SOURCE_SYNC_PRINTER_IDS=1
PLM_PUBLIC_URL=https://plm.example.local
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

### Phase A2: PLM-Slicerprojekt und Revision mit Druckarchiv verknüpfen

- [x] Laufende Bambuddy-Archive des explizit konfigurierten Druckers lesen.
- [x] Ausschließlich den exakten Namen `<Teilnummer>_<Revisionscode>`
  akzeptieren und mehrdeutige PLM-Treffer überspringen.
- [x] Die aktuelle `slicer_project_3mf` per konkreter Archiv-ID als Source-3MF
  hochladen; vorhandene Source-Dateien niemals automatisch überschreiben.
- [x] Upload in PLM-Metadaten und Audit-Trail protokollieren.
- [x] Laufende und abgeschlossene Archive direkt mit der konkreten
  PLM-Revision verlinken; vorhandene externe Links nicht überschreiben.
- [x] Revisionslink in PLM-Metadaten und Audit-Trail protokollieren.
- [x] Worker-Kommando mit Dry-Run und standardmäßig deaktivierter Automatik.
- [x] Produktiven API-Key um `Manage Archives` ergänzen, Sync für Drucker-ID 1
  aktivieren und den laufenden A1-Druck verifizieren.

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

Nach der produktiven Abnahme des Source- und Link-Syncs folgt Phase B zunächst als
Metadatenimport. Die eingehende Zuordnung bleibt unabhängig vom sicheren,
exakten Source-Upload und darf weiterhin keine unscharfen Treffer übernehmen.
