# UI Redesign Plan

## Ziel

Das Web-UI soll sich wie ein ruhiger Desktop-Arbeitsplatz fuer FreeCAD-PLM anfuehlen:

- Projekt finden.
- Teil oder Baugruppe oeffnen.
- passenden Stand verstehen.
- Revision herunterladen, freigeben, exportieren oder kommentieren.
- neue Revision hochladen.
- Projektstand als ZIP importieren oder wieder herunterladen.

Die vorhandene Funktionalitaet bleibt erhalten. Der Umbau betrifft zuerst Struktur, Navigation, Informationsgewichtung und Komponenten, nicht das Datenmodell.

## Grundprinzipien

- Desktop first: 1200 bis 1600 px Breite sind der Hauptfall.
- Weniger Tabellen mit vielen Aktionsspalten, mehr Arbeitsbereiche mit klaren Primaeraktionen.
- Technische Details sind erreichbar, aber nicht Teil der Standardansicht.
- Der Hauptinhalt steht links, Kontext und Eigenschaften rechts.
- Aktionen stehen dort, wo die Arbeit passiert.
- Status, Revision und Dateiherkunft muessen auf einen Blick erkennbar sein.
- Snapshot, Exportjob und Metadaten sind Nebenpfade und werden als Panels oder Dialoge behandelt.
- Authentifizierung und Rollen bleiben im Hintergrund; keine neue Nutzerverwaltung im UI-Redesign.

## Framework-Entscheidung

Empfehlung: Django-Templates behalten, dazu Bootstrap 5 lokal ausliefern und kleine eigene Komponenten ergaenzen.

Begruendung:

- Passt zum bestehenden serverseitigen Django-Ansatz.
- Keine SPA-Komplexitaet fuer ein internes PLM.
- Gute, moderne Basiskomponenten fuer Buttons, Formulare, Modals, Offcanvas, Badges und Layout.
- Lokale Auslieferung bleibt moeglich.
- Spaeter kann HTMX punktuell fuer Dialoge, Inline-Updates und Filter nachgezogen werden.

Nicht empfohlen fuer diesen Schritt:

- React/Vue/Svelte als kompletter Rewrite. Das wuerde die eigentliche PLM-Arbeit blockieren.
- Reines Bootstrap ohne eigenes Designsystem. Dann wird es zwar technischer moderner, aber nicht automatisch einfacher.

## Ziel-Layout

### App-Shell

Jede Seite nutzt dieselbe Desktop-Shell:

- Obere Leiste: Produktname, globale Suche, angemeldeter Nutzer.
- Linke Seitenleiste: Hauptnavigation.
- Inhaltsbereich: arbeitsbezogene Ansicht.
- Rechte Kontextleiste: Eigenschaften, Status, letzte Aktionen, relevante Nebeninformationen.

Navigation links:

- Projekte
- Zuletzt bearbeitet
- Wartende Jobs
- optional spaeter: Suche, Einstellungen

Die linke Navigation ist auf Desktop dauerhaft sichtbar. Mobil darf sie einklappen, ist aber nicht der Hauptfall.

### Rechte Kontextleiste

Die rechte Leiste ist ein fester Bestandteil der Detailseiten:

- Projektseite: Projekteigenschaften, Status, Datum, Anzahl Teile, Anzahl Projektstaende.
- Teilseite: Teileigenschaften oder ausgewaehlte Revision.
- Vergleichsseite: Vergleichskontext und ausgewaehlte Revisionen.

Sie soll nicht endlos lang werden. Technische Details wie SHA-256, rohe FreeCAD-Metadaten oder vollstaendige Joblogs liegen in Dialogen.

## Informationsarchitektur

### Projekte

Standardansicht:

- Kopf: `Projekte`, Primaeraktion `Projekt anlegen`.
- Filterleiste: Status, Suche, archiviert ja/nein.
- Projektliste als kompakte Cards oder moderne Tabelle.

Pro Projekt sichtbar:

- Code und Name.
- Status-Badge.
- Datum.
- Anzahl Teile/Baugruppen.
- letzter Projektstand, falls vorhanden.
- Kurzbeschreibung nur einzeilig.

Primaere Aktion: Projekt oeffnen.

### Projekt-Detail

Ziel: Der Nutzer soll sofort die Teile/Baugruppen des Projekts sehen.

Layout:

- Header: Projektcode, Name, Status-Badge, Datum.
- Primaeraktion: `Teil/Baugruppe anlegen`.
- Sekundaeraktion: `Projektstand importieren`.
- Hauptbereich links: Teile und Baugruppen.
- Kontext rechts: Projekteigenschaften.
- Unterer Bereich: Projektstaende/Snapshots.

Teile/Baugruppen:

- Kompakte Tabelle mit Nummer, Name, Typ, neueste Revision, Status, geaendert.
- Klick auf Zeile oeffnet Teilseite.
- Optional Filter: Teil/Baugruppe, Status, Suche.

Projektstaende:

- Als eigener Abschnitt unterhalb der Teileliste.
- Import nicht als offenes Formular in der Seite, sondern Dialog `Projektstand importieren`.
- Snapshot-Details in Dialog oder aufklappbarem Detailbereich.

### Teil-/Baugruppen-Detail

Ziel: Diese Seite wird zum Revisionsarbeitsplatz.

Header:

- Teilenummer und Name.
- Typ-Badge `Teil` oder `Baugruppe`.
- Projektlink.
- Primaeraktion `Neue Revision hochladen`.
- Sekundaeraktionen `Visuell vergleichen`, `Jobs starten`.

Hauptbereich:

- Links: Revisionen als vertikale Liste oder kompakte Revisionskarten, nicht als breite technische Tabelle.
- Rechts: Eigenschaften der ausgewählten Revision oder des Teils.

Revisionseintrag sichtbar:

- Revisionscode.
- Status-Badge.
- Dateiname.
- Erstellungsdatum und Ersteller.
- kurze Notiz, falls vorhanden.
- Artefakt-Indikatoren: STEP/STL/3MF/PNG vorhanden.
- Jobstatus-Indikator, falls Jobs laufen oder fehlgeschlagen sind.

Primaere Aktionen pro Revision:

- `Laden` oder `Herunterladen`.
- `Freigeben`, falls erlaubt und Entwurf.
- `Anmerkungen`.
- Aktionsmenue fuer seltenere Dinge: `Objekte auslesen`, `Export planen`, `PNG-Ansichten`, `Metadaten`, `Jobs`, `Artefakte`.

Technische Details:

- SHA-256, Dateigroesse, FreeCAD-Rohmetadaten und Joblogs liegen im Dialog.
- In der normalen Revisionsliste werden sie nicht angezeigt.

Neue Revision:

- Upload als Dialog oder eigenes kompaktes Panel oberhalb der Revisionsliste.
- Felder: Datei, Aenderungsnotiz.
- PLMRevision-Konflikt bleibt als eigene Bestaetigungsseite, aber visuell an das neue Design angepasst.

### Revision-Vergleich

Ziel: Visueller Vergleich soll nicht wie eine technische Galerie wirken.

Layout:

- Auswahl zweier Revisionen oben als klarer Vergleichskopf.
- PNG-Ansichten in nebeneinanderliegenden Vergleichsframes.
- Wenn keine PNGs vorhanden sind: klare Aktion `PNG-Ansichten erzeugen`.
- Rechte Kontextleiste: Revisionen, Status, Artefaktstand.

### Formulare

Alle Formulare werden in ein einheitliches Muster gebracht:

- Einspaltig.
- Klare Feldgruppen.
- Primaerbutton unten links.
- Abbrechen/Zurueck als sekundaere Aktion.
- Keine Formulare als offene `details`-Elemente in Arbeitslisten.

Betroffene Formulare:

- Projekt anlegen/bearbeiten.
- Teil/Baugruppe anlegen.
- Revision hochladen.
- Projektstand importieren.
- Export planen.

## Komponenten

Neue UI-Komponenten:

- `app-shell`
- `sidebar-nav`
- `topbar`
- `page-title`
- `toolbar`
- `status-badge`
- `data-card`
- `object-list`
- `revision-card`
- `context-panel`
- `action-menu`
- `modal-dialog`
- `empty-state`
- `job-status-pill`
- `artifact-pill`

Diese Komponenten werden zuerst als Django-Template-Includes und CSS-Klassen umgesetzt. Keine neue Build-Pipeline im ersten Schritt.

## Designrichtung

Charakter:

- ruhig
- hell
- technisch, aber nicht hart
- dicht genug fuer Desktop-Arbeit
- klare Kanten, wenig Dekoration

Farben:

- neutraler Hintergrund
- weisse oder leicht getoente Arbeitsflaechen
- dezente Linien
- eine klare Akzentfarbe fuer Primaeraktionen
- Statusfarben nur fuer Status, nicht als Flaechenrauschen

Typografie:

- Systemfont oder lokal ausgelieferte, sachliche Sans-Serif.
- Kleine, klare Hierarchie.
- Keine grossen Marketing-Hero-Elemente.

Abstaende:

- Kompakter als jetzt.
- Einheitliche Skala.
- Tabellen und Listen mit stabiler Zeilenhoehe.

## Umsetzungsetappen

### Schritt 1: Designsystem und Shell

- Bootstrap 5 lokal einbinden.
- Altes Bootstrap 4 entfernen.
- Neue Basisstruktur in `base.html`.
- CSS-Variablen und Komponentenklassen anlegen.
- Linke Navigation und Topbar bauen.
- Bestehende Seiten in der neuen Shell lauffaehig halten.

Akzeptanz:

- Alle bestehenden Seiten rendern.
- Navigation ist konsistent.
- Keine Funktion geht verloren.

### Schritt 2: Projektuebersicht und Projekt-Detail

- Projektliste neu strukturieren.
- Statusfilter und Suche vorbereiten oder direkt serverseitig umsetzen.
- Projekt-Detail als Arbeitsansicht mit Teileliste links und Kontext rechts.
- Projektstand-Import in Dialog verschieben.
- Snapshotliste vereinfachen.

Akzeptanz:

- Projekt finden und oeffnen ist schneller.
- Teile/Baugruppen sind der klare Fokus der Projektseite.
- Projektstand-Import stoert die Standardansicht nicht mehr.

### Schritt 3: Teilseite als Revisionsarbeitsplatz

- Breite Revisionstabelle ersetzen.
- Revisionen als Cards oder kompakte Liste darstellen.
- Primaeraktionen sichtbar machen.
- Seltene Aktionen in Aktionsmenue/Dialoge verschieben.
- Artefakte, Jobs, Anmerkungen und Metadaten als Dialoge vereinheitlichen.

Akzeptanz:

- Revisionen sind ohne horizontales Scrollen lesbar.
- Technische Details sind erreichbar, aber nicht dominant.
- Upload, Download, Freigabe, Anmerkungen und Export sind klar auffindbar.

### Schritt 4: Vergleich, Upload-Konflikt und Exportplanung

- Visuellen Vergleich modernisieren.
- Upload-Konfliktseite klarer formulieren.
- Exportplanung als fokussiertes Formular ueberarbeiten.
- PNG-Fehlzustand mit naechster Aktion anzeigen.

Akzeptanz:

- Vergleich wirkt wie ein Arbeitswerkzeug.
- Konflikte sind verstaendlich und entscheidbar.
- Export-/PNG-Aktionen fuehren nachvollziehbar weiter.

### Schritt 5: Feinschliff und Regression

- Alle Seiten einmal auf Desktopbreiten pruefen.
- Texte vereinheitlichen: `Projektstaende`, `Oeffnen`, `Zurueck` spaeter auf echte Umlaute umstellen, falls wir UTF-8 konsequent zulassen.
- Fokuszustaende und Tastaturbedienung pruefen.
- Bestehende Tests anpassen.
- Falls sinnvoll: kleine Template-Tests fuer wichtige UI-Anker.

Akzeptanz:

- `manage.py check` ist gruen.
- bestehende PLM-Tests sind gruen.
- Kernablauf ist manuell pruefbar:
  - Projekt anlegen.
  - Teil mit FCStd anlegen.
  - Revision hochladen.
  - Revision herunterladen.
  - Revision freigeben.
  - Anmerkung bearbeiten.
  - Objekte auslesen / Exportjob anlegen.
  - Projektstand importieren und herunterladen.

## Offene Entscheidungen

- Revisionsdarstellung: Cards oder kompakte Liste?
  - Empfehlung: kompakte Liste mit aufklappbarem Detailbereich. Sie ist dichter und besser fuer viele Revisionen.
- Soll es eine globale Suche schon im ersten Redesign geben?
  - Empfehlung: visuell vorsehen, funktional spaeter ausbauen.
- Sollen Dialoge mit Bootstrap 5 oder eigenem Dialogsystem laufen?
  - Empfehlung: Bootstrap 5 Modals, wenn lokal und sauber eingebunden; sonst eigenes kleines Dialogsystem behalten.
- Sollen Icons eingesetzt werden?
  - Empfehlung: Ja, lokal eingebundene Bootstrap Icons oder einfache Inline-Symbole. Nicht ueberladen.

## Nicht Bestandteil dieses Plans

- Neues Rollen-/Rechtesystem.
- Token-Auth fuer das Addon.
- Neues Datenmodell fuer Stuecklisten.
- Vollstaendige SPA.
- Worker-Architektur-Umbau.
