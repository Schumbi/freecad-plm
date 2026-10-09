# Geometrische Bauteilvarianten

## Fachliches Modell

Geometrische Ausführungen wie Chipboxen für 10, 20 und 25 Chips bestehen
parallel. Jede Ausführung ist ein eigenes `Part` mit eigener Teilenummer,
Revisionshistorie und eigenen Druckprojekten. Eine optionale `PartFamily`
verbindet die Ausführungen. Bestehende Teile bleiben ohne Familie nutzbar;
beim Erstellen der ersten Variante wird die Familie automatisch angelegt.

`Part.variant_source_revision` hält die konkrete Herkunft fest. Parameter
werden ausschließlich in FreeCAD bearbeitet und vollständig in den FCStd-Dateien
gespeichert. Es gibt keinen zusätzlichen Parametereditor im Server.

## FreeCAD-Ablauf

1. Ausgangsrevision aus dem PLM öffnen oder auschecken.
2. Parameter in FreeCAD ändern. Ungespeicherte Änderungen in geöffneten
   Referenz- und Parameterdateien werden beim Erstellen der Variante übernommen.
3. Im Browser die gewünschte Hauptrevision wählen, beispielsweise `Druck.FCStd`.
   Das aktive FreeCAD-Dokument muss zum Dateisatz dieser Revision gehören;
   es darf also auch die zugehörige `Chip.FCStd` sein.
4. Unter „Mehr“ die Aktion „Als neue Variante speichern“ wählen und Name
   sowie optional eine Teilenummer eingeben.
5. Der Server speichert die Variante mit R0001 und öffnet einen eigenen Checkout.
   Vorhandene Quelldokumente werden weder gespeichert noch geschlossen.
   Ein vorheriger Checkout bleibt erhalten und kann über die Checkout-Liste
   wieder geöffnet werden.
6. Spätere Änderungen dieser Ausführung wie gewohnt einchecken.
7. Für die Variante ein eigenes Druckprojekt erstellen und die vorbereitete
   3MF speichern. Beim nächsten Druck dieses bestehende Druckprojekt öffnen.
   Die bestehende Bambuddy-Anbindung bleibt der Weg zum archivierten Druckstand.

„Varianten anzeigen“ erlaubt im Add-on den Wechsel zwischen Mitgliedern einer
Familie. Die Web-Teilseite zeigt Familie, Varianten und Herkunftsrevision.

## Verknüpfte Modelle

Die Chipbox enthält eine Parameterdatei, Box, Deckel und ein Druckmodell.
Deshalb wird der vollständige transitiv referenzierte Dateisatz kopiert.
Auch abhängige Dateien erhalten eigene Teile, Familienzuordnung und R0001;
die ursprünglichen Teile und Revisionen werden nicht verändert. Originale
relative Dateipfade bleiben im neuen Projektstand erhalten. Externe XLinks
werden eindeutig auf diesen Dateisatz umgestellt; Dokument-IDs werden neu
vergeben. Die Chipbox-BOM-Dateipfade werden ebenfalls angepasst.

Das Add-on berechnet Parameterdateien vor abhängigen Geometriedokumenten neu
und verwendet `saveCopy`. Geschlossene Referenzdateien werden aus dem lokalen
PLM-Dateisatz übernommen. Fehlende Dateien, zusätzliche oder nicht eindeutig
auflösbare Referenzen verhindern die Anlage. Neue externe Abhängigkeiten
müssen zunächst über den regulären PLM-Ablauf gespeichert werden.

## Server und Rechte

Migration 0027 ergänzt ausschließlich optionale Teilefelder und die Familientabelle.
Vor Nutzung Servermigration anwenden und Server sowie Add-on gemeinsam aktualisieren.

Der bestehende Multipart-Endpunkt
`POST /api/projects/<id>/parts/create-fcstd/` akzeptiert für Varianten:

- `source_revision_id`: Herkunftsrevision im selben Projekt.
- `source_snapshot_id`: optional der konkrete Ausgangsprojektstand.
- `name`, optional `number`.
- `file`: ZIP mit genau Hauptdatei und Referenzdateien, bei Einzelmodellen
  alternativ eine FCStd-Datei.

Varianten erhalten immer einen eigenen Checkout. Erforderlich sind
Editor-/Adminrechte sowie Token-Scopes `write` und `checkout`; zum Navigieren
im Add-on zusätzlich `read`. Die Serverprüfung ist verbindlich.
`GET /api/parts/<id>/` liefert `variants` und `can_create_variant`.
Teilepayloads enthalten Familie und Herkunft; Manifestdateien enthalten
`reference_files` für die Reihenfolge der Neuberechnung.

Die Anlage von Teilen, Revisionen, Familie, Projektstand und Checkout erfolgt
atomar. Dateien eines fehlgeschlagenen Variantenuploads werden entfernt.
Vorhandene 3MF-Dateien und Druckprojekte werden nicht automatisch kopiert,
weil ihre Geometrie und Druckeinstellungen zur ursprünglichen Ausführung gehören.

## Prüfung

Automatisierte Tests prüfen Rollen und Scopes, unabhängige Revisionen,
Referenzgraph, Herkunft, Familiennavigation und Rollback einschließlich Dateien.
Die Repository-Chipbox wird mit `Box_anzahlChips = 20` gespeichert;
der ursprüngliche Stand bleibt bei 25. Add-on-Tests prüfen ungespeicherte
Parameter, Reihenfolge der Neuberechnung und unveränderte Quelldateien.
Ein HTTP-Vertragstest verbindet den echten Add-on-Client mit dem Server und
prüft Variantenanlage sowie Speicherung und erneuten Download einer eigenen 3MF.

Manuelle Abnahme mit echtem FreeCAD/Slicer und Bambuddy steht noch aus:
10er- und 20er-Variante erstellen, Geometrie prüfen, einchecken, jeweils eigenes
Druckprojekt vorbereiten, erneut öffnen und erfolgreichen Druck wiederholen.
