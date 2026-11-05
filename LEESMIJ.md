# Twinly · lokale preview 0.4.0

Een native richtexteditor met GTK4/libadwaita voor Linux/GNOME. Deze map is de
volledige applicatie. Er is geen server, account, browser of internetverbinding
nodig tijdens het gebruik. Markdown is niet opgenomen.

## Bestaande installatie bijwerken

Sluit Twinly. Kopieer **alle .py-bestanden** uit deze uitgave naar je bestaande
appmap, inclusief de nieuwe modules. Alleen editor.py vervangen is bij deze
revisie niet voldoende. Laat je mappen Documenten en Instellingen staan.
De bestaande HTML-bestanden en voorkeuren blijven bruikbaar.

## Starten op Arch Linux

1. Pak `Twinly-preview.zip` uit. Je krijgt de aparte map `Twinly-preview`.
2. Installeer eenmalig de systeemafhankelijkheden in een terminal:

   ```bash
   sudo pacman -S python python-gobject python-cairo gtk4 libadwaita
   ```

3. Open de uitgepakte map in GNOME Bestanden. Rechtsklik op een lege plek en kies
   **Openen in terminal**. Start:

   ```bash
   bash start.sh
   ```

4. Bij een nieuwe installatie opent `Start to note.html` automatisch. Dit Engelstalige document bevat alle functies en een ingebedde foto.

Gebruik de systeem-Python; geen pip of virtualenv nodig. Vereist GTK ≥ 4.12 en
libadwaita ≥ 1.4. De broncode hoeft niet gecompileerd te worden.

Voor Ubuntu 24.04 en later zijn de overeenkomstige pakketten:

```bash
sudo apt install python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
bash start.sh
```

## Alles staat apart

- `Documenten/`: standaardhoofdmap met echte mappen en zelfstandige HTML-bestanden.
- `Instellingen/voorkeuren.json`: bewaart hoofdmap, uiterlijk en werkruimte.
  Bestaande instellingen worden automatisch naar het huidige schema bijgewerkt.
- De code en tests blijven binnen deze projectmap.

Je kunt de hele previewmap verplaatsen. Documenten in een zelf gekozen externe
hoofdmap worden daardoor niet mee verplaatst. Kies die hoofdmap opnieuw als die
zelf is verhuisd.

Een bestaande hoofdmap rechtstreeks openen kan ook:

```bash
bash start.sh --root /volledig/pad/naar/documenten
```

## Prullenbak

Het prullenbakicoon onderaan de sidebar opent binnen Twinly de verwijderde
HTML-documenten en mappen uit de huidige hoofdmap. Terugzetten herstelt de
oorspronkelijke locatie; bestaande bestanden worden niet overschreven.
Het overzicht gebruikt de GNOME-systeemprullenbak en vereist GVfs. Er is een
knop Vernieuwen om externe wijzigingen op te halen. Prullenbak leegmaken verwijdert na bevestiging uitsluitend de getoonde
items uit de huidige hoofdmap definitief. Dit kan niet ongedaan worden
gemaakt; items uit andere hoofdmappen blijven behouden.

## Documentenmap openen

Het zoekicoon onderaan de zijbalk toont een doorzoekbaar documentenoverzicht binnen Twinly.
Daarin staan de HTML-bestanden uit de hoofdmap en submappen. Aanklikken opent
het document in onze editor. Er wordt geen externe bestandsbeheerder geopend.
Een andere hoofdmap kiezen blijft via het menu mogelijk.

## Terug en vooruit

Uiterst links in de headerbalk van het rechterpaneel staan Terug en Vooruit.
Ze navigeren door geopende documenten en het documentenoverzicht. Je kunt ook
Alt+Links en Alt+Rechts gebruiken. De knoppen zijn uitgeschakeld als er geen
bestemming is. Een nieuwe navigatie na Terug vervangt de vooruitgeschiedenis.
Onopgeslagen werk blijft beschermd. Dit is afzonderlijk van Ongedaan maken
en Opnieuw voor tekstbewerkingen.

## Menu’s

Het hamburgermenu in de sidebar bevat algemene functies en mapbeheer.
Het documentmenu rechtsboven bevat de functies voor het actieve document.
De contextmenu’s passen zich aan het aangeklikte item aan.

## Contextmenu per item

Bij een document staan Hernoemen, Verplaatsen, Naar prullenbak,
Afdrukvoorbeeld en Afdrukken. Afdrukken opent rechtstreeks de printerdialoog.
Deze acties gebruiken het aangeklikte document; bij het geopende document
wordt de actuele tekst inclusief niet-opgeslagen wijzigingen gebruikt.
Nieuwe map, Nieuw document en Hoofdmap kiezen staan uitsluitend bij mappen
of lege zijbalkruimte. Nieuwe hoofdmap staat alleen in het hamburgermenu.

## Zijbalkknoppen

De losse knop Nieuw document en het icoon Nieuwe map zijn verwijderd.
Nieuwe documenten en mappen maak je aan via het contextmenu.

## Hoofdmap aanmaken (0.3.5)

Alleen het hamburgermenu bevat **Nieuwe hoofdmap…**. Via die optie maak je
een nieuwe hoofdmap binnen de app aan. **Hoofdmap kiezen…** in het
contextmenu gebruikt uitsluitend bestaande mappen. De onderste mapknop opent
het documentenoverzicht binnen Twinly.

## Zijbalk en hoofdmap (0.3.4)

De losse knop Nieuw document is verwijderd. Rechtsklik op een map, document
of lege ruimte in de zijbalk voor het contextmenu. Op lege ruimte worden
nieuwe items in de hoofdmap geplaatst. Via Hoofdmap kiezen… kun je een
bestaande map kiezen. Alleen Nieuwe hoofdmap… in het hamburgermenu kan een
nieuwe hoofdmap maken.

## Correctie contextmenu (0.3.3)

Contextmenu’s zijn gekoppeld aan de vaste lijst in plaats van aan een
herbruikbare maprij. Map- en documentacties worden uitgevoerd nadat GTK de
menuactie heeft afgehandeld. Dit voorkomt dat een menu aan een verwijderde
rij blijft hangen tijdens het vernieuwen van de boom.

## Vernieuwde GNOME-zijbalk

De zijbalk gebruikt native `Gtk.ListView`, `Gtk.TreeListModel` en
`Gtk.TreeExpander`, met de officiële libadwaita-stijl `navigation-sidebar`.
De zijbalk loopt over de volledige vensterhoogte en heeft een eigen
`Adw.HeaderBar` en `Adw.ToolbarView`, afgeronde selectierijen en een
knop voor de hoofdmap. Eén klik opent een document; pijltjes klappen mappen uit.
Op smalle vensters verschijnt de zijbalk als inklapbaar overlaypaneel.

## Documenttitel wijzigen

Klik op de documentnaam midden in de rechter headerbalk om die rechtstreeks
te wijzigen. Enter bevestigt; Escape annuleert. Het HTML-bestand wordt
hernoemd, de zijbalk en navigatie worden bijgewerkt en onopgeslagen tekst
blijft behouden. Een bestaande naam wordt niet overschreven. Bij een nog
naamloos document opent Opslaan als met de ingevulde naam.

## Direct arceren via rechtsklik

Selecteer tekst en klik rechts: de vijf kleurvakjes staan meteen in het
contextmenu, naast de standaardopties knippen, kopiëren en plakken. Er is geen
submenu nodig. Ook Shift+F10 en de menutoets tonen dit menu bij een selectie.
De geselecteerde tekst blijft geselecteerd na het kiezen van een kleur.

## Opmaakbalk

Vet, cursief, onderstrepen en doorhalen vormen één aaneengesloten knopgroep.
Ongedaan maken en Opnieuw vormen een tweede knopgroep, rechts uitgelijnd aan
het einde van de opmaakbalk. Opmaak verwijderen staat direct links daarvan.
Arceren, uitlijning en foto invoegen vormen samen een aaneengesloten groep.
De overige bediening kan omlopen bij smalle vensters.

## Lettertypevarianten

De lettertypekiezer verwerkt ook de gekozen variant: bijvoorbeeld Light,
Semibold, Bold, Italic, Oblique en Condensed. Welke varianten je kunt kiezen
hangt af van de geïnstalleerde lettertypen. De variant wordt behouden in HTML
en in de gedeelde afdruk/PDF-opmaak. Regular kiezen verwijdert vet/cursief;
het kiezen van een lettertype is één stap voor Ongedaan maken.

## Lijn en lettertype

De knop met het horizontale streepje voegt op de cursorpositie een echte
scheidingslijn in. Deze wordt als `<hr>` opgeslagen in HTML en verschijnt ook
in het afdrukvoorbeeld en de PDF. Verwijderen kan met Backspace/Delete of
Ongedaan maken. Lettertype en grootte kies je samen via één lettertypeknop;
de losse grootteknop is verwijderd.

## Functies

- Lettertype en tekstgrootte voor geselecteerde tekst.
- Vet, cursief, onderstrepen, doorhalen en opmaak wissen.
- Alinea-uitlijning: links, midden, rechts en uitgevuld.
- Arceren in geel, groen, blauw, roze en oranje, plus arcering verwijderen.
- Rechtsklikken op een tekstselectie: standaard tekstmenu met extra arceeropties;
  de kleurvakjes staan bij een tekstselectie rechtstreeks in het menu. Shift+F10 opent het tekstmenu.
- Foto’s invoegen (PNG/JPEG), aanklikken voor breedte aanpassen en verwijderen.
  De beeldverhouding blijft behouden.
- Editorzoom via −/+ rechtsonder; wijzigt de opgeslagen lettergrootte niet.
- Ongedaan maken en opnieuw, inclusief opmaak en foto’s (laatste 60 stappen).
- Openen en opslaan als één `.html` met ingebedde foto’s.
- Mappenboom met geneste uitvouwbare schijfmappen en HTML-documenten.
- Rechtsklik of plusmenu: nieuwe map, nieuw document, hernoemen, verplaatsen en
  naar de prullenbak sturen. Nieuwe map maakt direct `nieuwe map` aan, zonder naamdialoog. Nieuw document
  maakt direct `nieuw document.html` aan. Beide verschijnen meteen onder de
  map van het contextmenu; de bovenliggende mappen worden uitgeklapt.
  Bij bestaande namen volgt een nummer, bijvoorbeeld `nieuw document 2.html`.
  Hernoemen kan daarna via het contextmenu. Bij onopgeslagen tekst vraagt de
  editor pas na het aanmaken of je van document wilt wisselen.
- Mappen verplaatsen via slepen op een andere map, of **Verplaatsen naar…**.
  Kies de hoofdmap in die dialoog om iets naar het hoogste niveau te verplaatsen.
- Live bijwerken na wijzigingen via GNOME Bestanden. Open bestandspaden volgen
  herkenbare verplaatsingen. Bij externe inhoudswijzigingen kun je herladen of
  je huidige versie behouden. Opslaan vraagt bevestiging voor overschrijven.
- Inklapbare zijbalk; onder 760 px werkt de zijbalk als overlay.
- Waarschuwingen bij onopgeslagen wijzigingen en naamconflicten.

## Afdrukvoorbeeld

Het printerpictogram opent het afdrukvoorbeeld met paginering. Je kunt kiezen
uit A4, A5 en Letter, staand of liggend, en marges van 5–40 mm.

**PDF opslaan…** en **Afdrukken…** gebruiken dezelfde Pango/Cairo-paginaopbouw als
het voorbeeld. De systeemdialoog laat je een printer kiezen. Laat voor een
1:1-afdruk het papierformaat overeenkomen met het voorbeeld; de geselecteerde
pagina wordt zo nodig passend geschaald als een ander papierformaat is gekozen.

De editor zelf heeft doorlopende tekst. Bij afdrukken worden foto’s als een
apart blok geplaatst; tekst ernaast kan daardoor anders afbreken. Het
voorbeeld toont de daadwerkelijke afdrukopbouw. Een andere toepassing kan
HTML met een andere typografie afdrukken.

## Sneltoetsen

| Actie | Toetsen |
|---|---|
| Nieuw / Openen | Ctrl+N / Ctrl+O |
| Opslaan / Opslaan als | Ctrl+S / Ctrl+Shift+S |
| Vet / Cursief / Onderstrepen | Ctrl+B / Ctrl+I / Ctrl+U |
| Ongedaan / Opnieuw | Ctrl+Z / Ctrl+Shift+Z of Ctrl+Y |
| Afdrukvoorbeeld | Ctrl+P |
| Venster sluiten | Ctrl+W |
| Tekstcontextmenu | Shift+F10 |

## Grenzen van deze preview

- Geen tabellen, vaste editorpagina’s, ODT/DOCX of Markdown.
- HTML-import ondersteunt het eenvoudige opmaakdeel dat deze editor gebruikt,
  waaronder inline lettertypen, kleuren, uitlijning en ingebedde PNG/JPEG.
  Complexe webpagina’s, externe CSS, tabellen en links worden niet volledig
  behouden. Externe foto-URL’s worden niet opgehaald.
- Alleen PNG/JPEG-foto’s, maximaal 20 MB per foto en 50 megapixels. HTML-documenten
  maximaal 64 MB. Grote foto’s vergroten het HTML-bestand en het geheugengebruik.
- Foto’s kun je via de contextbalk schalen; vrije tekstomloop en slepen aan
  afbeeldingshoeken zijn niet inbegrepen.
- De mappenboom toont HTML-bestanden en mappen; verborgen bestanden en
  symbolische links worden overgeslagen. Maximaal 2000 mappen worden bewaakt.
  Netwerkschijven kunnen minder betrouwbare wijzigingsmeldingen geven.
- De prullenbak vereist ondersteuning van je desktop/bestandssysteem. Als dat
  niet beschikbaar is, verschijnt een fout; er wordt niet definitief verwijderd.
- Automatisch opslaan gebeurt ongeveer twee seconden na een wijziging.
  Nieuwe documenten uit de zijbalk hebben direct een bestandsnaam. Tekst in
  een nog naamloos startdocument vereist eerst Opslaan. Ctrl+S blijft werken.
  Externe wijzigingen pauzeren automatisch opslaan en worden niet stilzwijgend
  overschreven. Een opslagfout verschijnt in de statusbalk; Ctrl+S probeert opnieuw.
  Er is geen herstelbestand voor wijzigingen tijdens de laatste twee seconden
  vóór een crash. Sluitwaarschuwingen blijven actief bij niet-opgeslagen tekst.

## Verificatie

De applicatie is gestart en visueel bekeken met GTK 4.14 en libadwaita 1.5 in een
virtuele X11-sessie. Tests controleren HTML-rondreizen, ingebedde foto’s,
bestandsverplaatsingen, live mapupdates, tekstopmaak, zoom zonder
opslagwijziging, undo/redo, fotoverwijdering en de gedeelde PDF/preview-paginering.
Een echte printer en jouw Arch/GNOME-installatie konden hier niet worden getest.

Tests uitvoeren in een grafische sessie:

```bash
python3 -m unittest discover -s tests -v
```

Bronnen: https://docs.gtk.org/gtk4/ en
https://gnome.pages.gitlab.gnome.org/libadwaita/doc/1.0/.

## Zoeken in het document

Klik op het vergrootglas in de rechter titelbalk of druk Ctrl+F. Typ je zoektekst; zoeken negeert hoofdletters. De pijlen en Enter/Shift+Enter gaan naar het volgende/vorige resultaat. Escape of het kruisje sluit de zoekbalk. Zoekmarkeringen worden niet opgeslagen.

## Fotoformaat met de muis

Klik op een foto. De selectierand heeft vier hoekgrepen. Sleep een hoek om proportioneel te vergroten of verkleinen. Eén sleepbeweging is één stap voor Ongedaan maken. De breedte kan ook in pixels worden ingevuld.

## Kopie maken

Gebruik het icoon met twee documenten naast Opslaan of rechtsklik op een document in de sidebar en kies Kopie maken. De kopie staat in dezelfde map en opent meteen. De naam krijgt – kopie, met een volgnummer als dat nodig is. Bij het huidige document worden ook niet-opgeslagen wijzigingen meegenomen.

## Vernieuwde interface

Rustige opmaakbalk met actieve opmaak, gecentreerde schrijfbreedte op brede schermen, compacte sidebar en zwevende foto-opties. De titel toont de bewaarstatus. Licht/donker volgt GNOME. In smalle vensters staan Openen en Kopie maken in het compacte documentactiemenu. Grote afbeeldingen passen op het scherm zonder hun opgeslagen formaat te wijzigen.

## Documentlinks en externe links

Klik op het kettingicoon of druk Ctrl+K. Kies Documentlink (purper onderlijnd) of Externe link (blauw onderlijnd) en vul de weergavetekst in. Geselecteerde tekst wordt ingevuld. De documentkeuze is doorzoekbaar. Interne links worden relatief aan het opgeslagen bronbestand bewaard; bij een nieuw document wordt eerst een opslaglocatie gevraagd. Een gewone klik opent een documentlink. Ctrl+klik opent een externe weblink. Via rechtsklik op de link kun je openen, bewerken of de link verwijderen met behoud van de tekst. De links blijven gewone HTML-hyperlinks. Bij hernoemen of verplaatsen binnen Twinly worden interne verwijzingen in HTML-documenten onder de gekozen hoofdmap automatisch bijgewerkt. Dit geldt ook voor hele mappen, uitgaande links en de nog niet opgeslagen inhoud en undo-geschiedenis van het geopende document. Bestanden buiten de hoofdmap kunnen niet worden bijgewerkt.

## Twee documenten naast elkaar

Klik rechts op een HTML-document in de sidebar en kies **Naast huidig document openen**. Dit kan ook via het documentmenu rechtsboven. De scheidingslijn is versleepbaar. Klik in een document om de gedeelde opmaakbalk daarop toe te passen. Beide documenten behouden een eigen buffer, geschiedenis en automatische opslag. Sluit een deelvenster met het kruisje in de bijbehorende titelbalk. Bij niet-opgeslagen wijzigingen verschijnt de gebruikelijke opslagvraag. Via het contextmenu van een interne documentlink kun je **Link hiernaast openen** kiezen. Hetzelfde bestand wordt niet tegelijk in twee bewerkbare deelvensters geopend.

Klik op een interne documentlink voor **Hier openen** of **Hiernaast openen**. Vanuit rechts betekent hiernaast het linker deelvenster. Een reeds geopend doel krijgt de focus zonder opnieuw te laden.

### Deelvensters beheren

Het actieve deelvenster krijgt een accentlijn onder de titelbalk. Elk deelvenster heeft eigen terug- en vooruitknoppen. In het documentmenu staan **Deelvensters verwisselen** en **Vastzetten als referentie**; de punaise in de titelbalk zet een document vast of maakt het los. Documenten die je vanuit de sidebar opent vervangen een niet-vastgezet document. Zijn beide documenten vastgezet, maak dan eerst één ervan los.

- **F6**: wisselen tussen de deelvensters.
- **Ctrl+W**: actief deelvenster sluiten, of de app sluiten als er maar één is.
- **Ctrl+Q**: de volledige app afsluiten.

Bij normaal afsluiten worden de geopende opgeslagen documenten, de breedteverdeling, links/rechts-volgorde, actieve pagina, zoom, cursor, scrolposities en vastgezette referenties onthouden. Bij een volgende start worden bestaande bestanden opnieuw geopend. Niet-opgeslagen wijzigingen krijgen eerst de gebruikelijke opslagvraag.

### Rustige werkruimte

Eén algemene headerbar en één opmaakbalk bedienen het actieve document. Boven elke pagina staat alleen de aanklikbare titel, met een kort accentstreepje bij het actieve document. Het sluitkruisje verschijnt wanneer je de titelrij aanwijst. Rechtsklik op de titel voor hernoemen, vastzetten of losmaken, verwisselen en sluiten. De punaise is alleen zichtbaar bij een vastgezet document. Eén zoompil rechtsonder volgt het actieve document. Dezelfde opbouw blijft behouden wanneer één document openstaat.

## Technische revisie

Documentgegevens, instellingen, werkruimte, acties, thema en editorweergave zijn opgesplitst in eigen modules. Het tweede deelvenster is een GTK-widget met een zelfstandige documentsessie en deelt de sidebar en mapbewaking. Documenten worden gevalideerd vóór laden en opslaan. Fouten bij automatisch opslaan blijven zichtbaar met een herstelknop. De bestandsdialogen gebruiken Gtk.FileDialog. Zie REVISIE.md voor controles, meetresultaten en beperkingen.

## GitHub en Flatpak

Zie README.md voor de Engelstalige projectinformatie en docs/PUBLISHING.md voor publicatie. Het project bevat een Flatpak-manifest en GitHub Actions-workflows. De definitieve GitHub-identiteit en projectlicentie moeten nog worden ingevuld. Een echte Flatpak-build en tests in de sandbox blijven nodig voor publicatie.

## Veiligheidsmaatregelen

Zie SECURITY.md voor importlimieten, bevestiging bij links buiten de hoofdmap, veilige bestandsbewerkingen en privéstandaarden. Flatpak gebruikt bestandsportalen en een herstelbare privéprullenbak in de gekozen bibliotheek; de native app behoudt GNOME’s prullenbak. HTML-bestanden zijn niet versleuteld.
