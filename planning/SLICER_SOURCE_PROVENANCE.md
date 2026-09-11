# CAD-Quellenstand in 3MF und bestätigte Neuerzeugung

Stand: 2026-09-12, Add-on-Version 0.1.3.

## Anlass

Beim Rodelbahn-Modell kann die Druckbaugruppe dieselbe Revision behalten,
während ein neuer Projektstand eine andere Deckelrevision enthält. Ein bereits
vorhandener Slicer-Arbeitsstand wird wiederverwendet und dadurch nicht automatisch
mit neuer CAD-Geometrie versehen.

## Umsetzung

- Neue CAD-Exporte enthalten `Metadata/freecad_plm_sources.json`, Schema 1,
  mit bereinigter Serveradresse, Projekt-ID, Hauptrevision, Exportzeit und
  vollständiger CAD-Dateiliste aus genau dem heruntergeladenen Manifest.
  Pro Datei: relativer Pfad, Teil-/Revisions-ID, Revisionscode, SHA-256 und
  Kennzeichnung der Hauptdatei. Keine Tokens oder Download-URLs.
- Der Vergleich beim Öffnen erkennt geänderte, ergänzte und entfernte
  Abhängigkeiten. Die Reihenfolge des Manifests ist unerheblich.
- Fehlende, ungültige oder unbekannte Metadaten gelten als nicht prüfbar.
  Entfernt ein Slicer den optionalen Metadatenteil beim Speichern, wird diese
  Einschränkung sichtbar, statt aktuelle Quellen nachträglich zu behaupten.
- Bei Abweichung oder unbekannter Herkunft: bestätigtes Neuerzeugen,
  bisherigen Stand öffnen oder abbrechen. Zusätzlich manuelle Aktion unter
  `Mehr → 3MF neu erzeugen`. Abbrechen ist die Standardauswahl.
- Export aus isoliertem temporären Verzeichnis mit genau dem zuvor geprüften
  Manifest. Erst nach erfolgreichem Export und Validierung Sicherung der
  bisherigen lokalen 3MF und des Sync-Zustands, dann atomarer Dateiaustausch.
  Gleichzeitiges Speichern im Slicer während des Exports bricht den Austausch ab.
- Die Dateiüberwachung pausiert während dieses Ablaufs und wird bei einem
  Fehler oder Abbruch wieder aktiviert.

## Grenzen

Die Metadaten dokumentieren den CAD-Export. Sie garantieren nicht, dass die
Geometrie anschließend im Slicer unverändert geblieben ist. Zusätzliche
Druckprojekt-Quellen werden durch die Neuerzeugung nicht automatisch eingefügt.
Ein automatischer Geometrieaustausch mit Erhalt von Druckeinstellungen,
Anordnung und Farben ist nicht Bestandteil dieses Schritts. Der bestehende
Server-Synchronisationsmechanismus wird unverändert verwendet; die Sicherung
liegt lokal. Es gibt keine automatische Migration vorhandener 3MF.

## Abnahme

Automatisierte Tests decken Quellenänderungen trotz unveränderter Hauptrevision,
fehlende Metadaten, Erhalt bestehender Archivteile, Dialogentscheidungen,
Sicherungen, Export-/Sicherungsfehler und Speichern während des Exports ab.
Zusätzlich mit FreeCADCmd 1.1.3 geprüft: Ein echter 3MF-Export eines Quaders
lässt sich nach Einfügen der Quellenmetadaten unverändert wieder als Mesh
laden (12 Dreiecke, Volumen 6000 mm³); der Quellenvergleich meldet aktuell.
Eine manuelle Abnahme des Dialogablaufs mit FreeCAD und Bambu Studio/OrcaSlicer
inklusive Metadatenverhalten nach dem Speichern bleibt erforderlich.
