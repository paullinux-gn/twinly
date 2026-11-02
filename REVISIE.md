# Twinly — uitgevoerde revisie

De technische revisie is uitgevoerd met behoud van het HTML-formaat, de bestaande functies en de rustige indeling. De Over-sectie is bewust niet uitgebreid.

## Uitgevoerde wijzigingen

- Eigen DocumentSession per document. Het tweede deelvenster is nu een EditorPane/GTK-widget, zonder tweede applicatievenster of extra sidebar en mapmonitors.
- Werkruimte, acties, voorkeuren, sessiestaat, instellingen, thema, editorweergave en callbackbeheer hebben eigen modules.
- Centrale validatie van tekst, opmaakbereiken, ankers, afbeeldingsmaten, links en opmaakwaarden vóór laden, exporteren en afdrukken. Onjuiste gegevens worden afgewezen voordat de editorbuffer wordt vervangen.
- JSON-voorkeuren moeten een object zijn; beschadigde data en niet-eindige getallen vallen terug op veilige waarden. Opslag gebruikt schema_version 1 en behoudt andere geldige instellingen.
- Een mislukte/gepauzeerde automatische opslag krijgt een blijvende banner met een herstelknop. Technische waarschuwingen worden gelogd; gewone succesmeldingen blijven stil.
- Tijdelijke callbacks, bestandsdialogen, popovers, monitors en CSS-providers worden opgeruimd. Opruimen kan veilig meermaals worden aangeroepen.
- Statische CSS wordt eenmaal per hoofdvenster geladen. Zoom heeft per document een unieke selector en kan het andere document niet meer onbedoeld beïnvloeden. Parsermeldingen bevatten regel en kolom. De ongebruikte popover-arrowregel is verwijderd.
- Voorkeurensliders geven direct visuele feedback, maar schrijven hun laatste instelling gebundeld na 250 ms naar schijf.
- Mapmonitors worden hergebruikt. Bij uitsluitend inhoudswijzigingen blijft de mappenboom intact; structurele wijzigingen herladen de boom en werken de monitorverzameling bij.
- HTML-import bouwt tekst via delen op in plaats van telkens de volledige tekst opnieuw samen te voegen. Printpaginering doorloopt alleen relevante opmaakbereiken.
- Afbeeldingen worden hergebruikt via een cache met een budget van 24 MiB. Te grote pixelafmetingen worden tijdens het voorbereiden van de decoder gedetecteerd. Undo blijft begrensd op 60 stappen en krijgt daarnaast een geheugenbudget van ongeveer 32 MiB; de huidige toestand blijft behouden als die zelf groter is.
- Hernoemen/verplaatsen werkt beide documentsessies bij. Opslaan naar het bestand dat in het andere deelvenster wordt bewerkt wordt geweigerd. Verwijderen houdt rekening met beide geopende documenten.
- Bestandsselectie gebruikt Gtk.FileDialog in plaats van de verouderde FileChooserNative-aanroepen.
- De uitgeschakelde werkbalk na het sluiten van een deelvenster is hersteld. Ongebruikte imports, een ongebruikte constante, lege statusafhandeling en overbodige code zijn verwijderd.

## Verificatie

**85 tests slagen** in de beschikbare GTK 4.14/Xvfb-omgeving. Dat omvat de 71 bestaande tests plus regressietests voor foutieve gegevens en voorkeuren, opslagfouten, sessies, monitorhergebruik, geannuleerde callbacks, bestandsdialogen, CSS, onafhankelijke zoom en werkbalkbediening na het sluiten van een deelvenster.

Licht en donker, de voorkeuren en een smal venster zijn visueel gecontroleerd. De interface is behouden. De geteste normale CSS geeft geen parserfouten.

## Meetresultaten

Meting tegen de vorige uitgave in dezelfde container. Mediaan van vier HTML-imports respectievelijk drie pagineringen. Dit zijn gerichte benchmarks, geen garantie voor dezelfde versnelling bij ieder document of op iedere computer.

| Test | Voor revisie | Na revisie | Resultaat |
| --- | ---: | ---: | --- |
| HTML-import, 8.000 alinea’s / 895.999 tekens | 237 ms | 43 ms | Ongeveer 5,5× sneller |
| Printpaginering, 1.800 opgemaakte alinea’s | 1.063 ms | 102 ms | Ongeveer 10,4× sneller; beide 55 pagina’s |

Bij het openen van een tweede document komt er geen extra applicatievenster bij. De sidebar en monitors worden gedeeld. Een inhoudswijziging veroorzaakt geen volledige herbouw meer van de mappenboom. Typreactie, opstarttijd en totaal geheugengebruik zijn niet als volledige vergelijkende benchmark gekwantificeerd; daarvoor wordt geen percentage geclaimd.

## Grenzen van de controle

De native GNOME/Wayland-blur kan in deze GTK 4.14/Xvfb-omgeving niet worden beoordeeld. De bestaande ondersteuning en de ondoorzichtige terugval blijven behouden. Werking op jouw compositor moet daar aanvullend worden bekeken. Een fysieke printer en een echte volle schijf zijn niet gebruikt; schrijffouten zijn gecontroleerd gesimuleerd. Er is geen crashherstel voor nog nooit opgeslagen documenten toegevoegd.

De gesimuleerde opslagproblemen produceren bewust waarschuwingen in de testuitvoer. EGL/DBus-waarschuwingen uit de headless testomgeving zijn geen CSS-parserfouten.

## Installatie van deze revisie

Sluit de app en kopieer **alle .py-bestanden** uit de ZIP naar je bestaande appmap. De nieuwe modules zijn noodzakelijk; alleen editor.py vervangen is niet voldoende. Laat Documenten en Instellingen staan. Start daarna zoals gewoonlijk met bash start.sh.
