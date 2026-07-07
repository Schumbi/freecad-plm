# FCStd Technical Signature Plan

## Zweck

Der Server soll beim Check-in nicht blind jede hochgeladene `FCStd`-Datei als
neue fachliche Revision behandeln. FreeCAD schreibt beim Speichern auch
technische und GUI-nahe Metadaten neu, obwohl sich das Modell nicht geaendert
hat. Der Server braucht deshalb eine eigene modellrelevante Signatur fuer
`FCStd`-Dateien.

Das Addon darf diese Pruefung weiterhin vorab fuer UX und Effizienz nutzen. Die
verbindliche Entscheidung muss aber im Server liegen, weil der Server die
Vertrauensgrenze ist und spaeter auch andere Clients einchecken koennen.

## Beobachtetes FreeCAD-Verhalten

Beim Testen mit FreeCAD 1.1 wurden beim reinen Drehen/Speichern bzw. beim
Speichern einer Baugruppe folgende Aenderungen beobachtet:

- `GuiDocument.xml` kann sich aendern, ohne dass das Modell fachlich geaendert
  wurde.
- `Document.xml` kann sich aendern, obwohl nur Save-/Recompute-Zustand
  aktualisiert wurde.
- `LastModifiedDate`, `LastModifiedBy` und die vom Addon gesetzte
  `PLMRevision` duerfen nicht als fachliche Modelländerung zaehlen.
- XML-Attribute wie `status`, `stamp` und `Touched` koennen sich durch
  FreeCAD-Speichern oder Link-/Assembly-Aufloesung aendern.
- BREP-/Shape-Dateien (`*.brp`, `*.brep`) koennen als Cache neu geschrieben
  werden. Sie sind fuer Diagnose nuetzlich, sollten in der ersten Serverversion
  aber nicht allein eine neue Revision ausloesen.
- FreeCAD legt beim Speichern `.FCBak`-Dateien an; diese gehoeren nicht in die
  PLM-Revision.

## Anforderungen

Der Server soll eine normalisierte technische Signatur fuer `FCStd`-Dateien
berechnen:

- `FCStd` als ZIP oeffnen.
- `Document.xml` lesen.
- `Document.xml` normalisieren:
  - Properties mit diesen Namen entfernen:
    - `LastModifiedBy`
    - `LastModifiedDate`
    - `PLMRevision`
  - XML-Attribute mit diesen Namen aus allen Elementen entfernen:
    - `status`
    - `stamp`
    - `Touched`
  - Absolute lokale Checkout-Pfade in XML-Attributen auf den referenzierten
    `.FCStd`-Dateinamen normalisieren, z.B. aus
    `.../checkout-2/files/Box.FCStd` wird `Box.FCStd`.
  - Numerische XML-Attributwerte kanonisch formatieren; sehr kleine
    Floating-Point-Rundungsartefakte nahe `0` werden als `0` behandelt.
  - Attribute deterministisch sortieren.
  - rein formatierenden Whitespace in `text`/`tail` normalisieren.
  - `Properties/@Count` nach entfernten Properties aktualisieren.
- SHA-256 ueber die normalisierte `Document.xml` bilden.
- Optional zusaetzlich Diagnose-Hashes ueber BREP-Mitglieder bilden, aber nicht
  als alleinigen Grund fuer eine neue Revision verwenden.

## Check-in-Verhalten

Beim Check-in soll der Server die hochgeladenen Dateien gegen die jeweilige
Basisrevision vergleichen:

- Ist die normalisierte `Document.xml`-Signatur unveraendert, wird fuer diese
  Datei keine neue Revision angelegt.
- Ist nur `GuiDocument.xml`, `ShapeAppearance*`, ZIP-Metadaten, `.FCBak`,
  `LastModified*`, `PLMRevision`, `status`, `stamp`, `Touched`, BREP-Cache,
  lokaler Checkout-Pfad in BOM-/XML-Attributen oder winziges Placement-
  Floating-Point-Rauschen betroffen, wird keine neue Revision angelegt.
- Ist die normalisierte `Document.xml`-Signatur geaendert, wird wie bisher eine
  neue Revision erzeugt.
- Bei einem Multi-File-Check-in koennen einzelne Dateien herausgefiltert werden.
  Nur die fachlich geaenderten Dateien erzeugen Revisionen und Snapshot-
  Ersetzungen.
- Wenn nach Filterung keine Datei fachlich geaendert ist, soll der Server eine
  JSON-Antwort liefern, die der Client als "keine modellrelevanten Aenderungen"
  anzeigen kann. Kein HTML-500.

## Umsetzungsvorschlag

Ein neues Servermodul kapselt die Logik, z.B. `plm/fcstd_signature.py`:

- `normalized_fcstd_document_xml(file_or_path) -> bytes`
- `fcstd_document_signature(file_or_path) -> str`
- `fcstd_diagnostic_hashes(file_or_path) -> dict`
- `fcstd_model_changed(base_revision, uploaded_file) -> bool`

Die Signatur sollte beim Erzeugen einer Revision gespeichert werden, damit der
Check-in nicht dauerhaft alte Dateien erneut aus dem Storage normalisieren muss.
Falls eine Migration dafuer zu viel fuer den ersten Schritt ist, kann der Server
die Signatur zunaechst on demand aus der gespeicherten Basisdatei berechnen.

## API-Verhalten

Der vorhandene Multi-File-Endpunkt kann beibehalten werden:

- `files_metadata` beschreibt weiterhin die vom Client vorgeschlagenen Dateien.
- Der Server prueft jede Datei zusaetzlich mit der eigenen FCStd-Signatur.
- Herausgefilterte Dateien sollten in der Antwort optional sichtbar sein, z.B.
  `ignored_files`, damit das Addon eine gute Statusmeldung anzeigen kann.

Beispielantwort, wenn keine fachliche Aenderung uebrig bleibt:

```json
{
  "checkout": { "...": "..." },
  "revision": null,
  "revisions": [],
  "ignored_files": [
    {
      "path": "Druck.FCStd",
      "reason": "no_model_change"
    }
  ]
}
```

## Tests

Serverseitige Tests sollen mindestens diese Szenarien abdecken:

- `GuiDocument.xml` geaendert, `Document.xml` fachlich gleich: keine Revision.
- `LastModifiedDate`/`LastModifiedBy` geaendert: keine Revision.
- `PLMRevision` geaendert: keine Revision allein dadurch.
- XML-Attribute `status`, `stamp`, `Touched` geaendert: keine Revision.
- Nur BREP-Dateien geaendert: keine Revision in v1.
- Echte Modell-/Dokumenteigenschaft in normalisierter `Document.xml` geaendert:
  neue Revision.
- Multi-File-Check-in mit gemischten Dateien:
  nur fachlich geaenderte Dateien erzeugen Revisionen.
- Multi-File-Check-in mit ausschliesslich nicht-fachlichen Aenderungen:
  JSON-Antwort ohne neue Revision und ohne Checkout-Abschlussfehler.

## Offene Designentscheidung

Noch zu entscheiden ist, ob ein Check-in ohne fachliche Aenderung den Checkout
abschliesst oder aktiv laesst. Fuer den ersten Schritt ist empfehlenswert:

- keine Revision erzeugen,
- Checkout aktiv lassen,
- dem Client klar melden, dass keine modellrelevanten Aenderungen vorhanden
  sind.

Damit kann der Nutzer danach echte Aenderungen vornehmen und erneut einchecken.
