# memecoin-radar

Kommandozeilen-Werkzeug fuer Memecoin-Analyse auf Solana: On-Chain-Daten,
Rug-Filter, FOMO-Phasenerkennung, Positionsgroessen-Rechner und Handelsjournal.

Reines Python 3.11+, **keine externen Abhaengigkeiten**, keine Wallet-Anbindung,
keine privaten Schluessel.

---

## Wozu das hier gebaut ist

Beim Memecoin-Handel verlieren die meisten Teilnehmer Geld, und zwar aus drei
Gruenden, die alle nichts mit der Auswahl des "richtigen" Coins zu tun haben:

1. **Sie kaufen die Kerze, nicht den Token.** Wenn ein Coin in einer
   Signalgruppe auftaucht, ist die Bewegung bereits gelaufen. Der Kauf liefert
   denen den Ausstieg, die vorher drin waren.
2. **Sie setzen zu gross.** Bei einer realistischen Trefferquote von 20-30%
   ruiniert eine Positionsgroesse von 10% des Kapitals auch eine Strategie mit
   positivem Erwartungswert. Das ist Mathematik, keine Meinung.
3. **Sie fuehren kein Journal.** Man erinnert sich an den 8x-Gewinn und
   vergisst die dreissig Totalverluste - und haelt ein Minusgeschaeft fuer
   eine Strategie.

Dieses Werkzeug adressiert alle drei Punkte. Es sagt dir nicht, was steigen
wird - das kann niemand. Es sortiert aus, was mit hoher Wahrscheinlichkeit
auf null geht, und zwingt dich zu einer Positionsgroesse, die du ueberlebst.

## Was es nicht tut

- **Keine Kauf-/Verkaufsausfuehrung.** Kein Zugriff auf Wallets, kein
  Schluesselmaterial. Ein Analysewerkzeug kann keine Mittel verlieren.
- **Keine Signalgruppen, keine "Insider"-Tipps.** Warum nicht, steht unten.
- **Keine Kursprognosen.** Wer dir eine verkauft, verkauft dir etwas anderes.

---

## So benutzt du es (der einfache Weg)

**Es gibt nichts einzurichten und nichts auswendig zu lernen.**

1. Ordner herunterladen: auf [github.com/scwerxed/memcoin](https://github.com/scwerxed/memcoin)
   auf den grünen Knopf **Code** → **Download ZIP**, dann entpacken.
2. **Windows:** `start.bat` doppelklicken.
   **macOS/Linux:** Terminal im Ordner öffnen, `./start.sh` eingeben.
3. Es erscheint ein Menü. Zahl tippen, Enter.

```
   1   Ankündigung prüfen  - jemand kündigt einen Coin VOR dem Launch an
   2   Calls verwalten     - Liste, Promoter-Bilanz, Abgleich mit Launches
   3   Lagebericht         - was ist gerade heiß, was hält stand
   4   Token prüfen        - der Coin ist schon gestartet
   5   Markt durchsuchen   - was besteht gerade die Filter
   6   Monitor starten     - läuft dauerhaft, meldet Fundstücke
   7   Positionsgröße      - wie viel darf ich setzen
   8   Meine Trades        - Journal und Auswertung
   9   Beispiel ansehen    - Ausgabe ohne Internet
  10   Einrichtung         - Zugänge eintragen und testen
   0   Beenden
```

Fang mit **9** an - das zeigt dir an drei Beispielen, was das Werkzeug
ausgibt, ohne dass irgendetwas eingerichtet sein muss.

Wenn Python fehlt, sagt dir `start.bat` das und wo du es herbekommst. Bei
der Windows-Installation muss **"Add Python to PATH"** angekreuzt sein.

### Zugänge eintragen (optional, Menüpunkt 7)

Punkt **10** fragt die Zugänge nacheinander ab, **prüft jeden sofort** und
speichert sie in einer Datei `.env` im selben Ordner. Danach nie wieder.

Alles daran ist freiwillig - jede Frage lässt sich mit Enter überspringen.
Ohne Zugänge läuft das Werkzeug auch, nur langsamer und mit weniger
Prüfungen.

**Es wird nie nach einer Seed-Phrase oder einem privaten Schlüssel
gefragt.** Alle Zugänge sind reine Lesezugänge und können kein Geld
bewegen. Wer danach fragt, will dich bestehlen - ausnahmslos.

Die Datei `.env` enthält Geheimnisse. Sie steht in `.gitignore`, landet also
nicht auf GitHub. Trotzdem: nicht weitergeben, keine Screenshots davon.

---

## Der Weg für Fortgeschrittene

Wer lieber tippt, kann jeden Menüpunkt auch direkt aufrufen - das Menü
zeigt bei jedem Schritt an, welchem Befehl die Auswahl entspricht.

```bash
git clone https://github.com/scwerxed/memcoin.git
cd memcoin
python3 run.py demo
```

Unter Windows in PowerShell heisst der Befehl `python` statt `python3`
(oder `py`, falls sich der Microsoft Store meldet). Benoetigt wird Python
3.11 oder neuer.

### Zugänge ohne den Assistenten

Statt Menüpunkt 10 gehen auch Umgebungsvariablen - oder eine von Hand
angelegte `.env` im Projektordner:

```
SOLANA_RPC_URL=https://eu.fluxrpc.com?key=DEIN-SCHLUESSEL
RUGCHECK_API_KEY=dein-schluessel
RUGCHECK_BASE_URL=https://api.rugcheck.xyz
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=deine-chat-id
```

Bereits gesetzte Umgebungsvariablen haben Vorrang vor der Datei.

## Befehle

| Befehl | Zweck |
|---|---|
| `call add` | Ankuendigung vor dem Launch erfassen und pruefen |
| `call match` | Offene Calls mit gestarteten Token verknuepfen |
| `call promoters` | Bilanz: welcher Promoter kostet dich Geld |
| `check <mint>` | Einzelnen Token vollstaendig pruefen (nach dem Launch) |
| `report` | Lagebericht: was ist gerade auffaellig, was haelt stand |
| `scan` | Neue und beworbene Token durchsuchen und filtern |
| `size` | Positionsgroesse und Preiseinfluss berechnen |
| `math` | Erwartungswert und Ruinrisiko durchrechnen |
| `paper` | Handelsjournal fuehren und auswerten |
| `monitor` | **Dauerbetrieb:** neue Token erfassen, reifen lassen, bei Eignung melden |
| `watch <mint>` | Einzelnen Token beobachten, Phasenwechsel melden |
| `demo` | Beispielausgabe ohne Netzwerk |
| `setup` | Gefuehrte Einrichtung der Zugaenge |
| *(ohne Argument)* | Menuegefuehrte Bedienung |

### Der wichtigste Befehl

Wenn dir jemand einen Token schickt - in einer Gruppe, per DM, auf X:

```bash
python3 run.py check <mint-adresse> --bankroll 5000
```

Das beantwortet in ein paar Sekunden die einzige relevante Frage:
**bin ich hier frueh dran, oder bin ich der Ausstieg fuer jemand anderen?**

```
Bewertung   15/100  [###.................]  [NO-GO]
Phase      BLOWOFF
           Senkrechte Kerze bei einseitigem Kaufdruck. Wer JETZT kauft,
           liefert denen den Ausstieg, die vorher drin waren. Das ist
           der Moment, in dem Signalgruppen posten.

-- AUSSCHLUSSKRITERIEN -------------------------------------------------
  X  88% Kaeufe - eine koordinierte Kampagne baut gerade ihre Gegenseite
     auf. Du waerst die Gegenseite
```

### Weitere Beispiele

```bash
# Markt durchsuchen, nur was die harten Filter ueberlebt
python3 run.py scan --limit 30 --only-passing

# Positionsgroesse fuer einen konkreten Token, live
python3 run.py size --bankroll 5000 --mint <mint> --risk 1.5 --stop 35

# Was muss meine Strategie leisten, um zu tragen?
python3 run.py math --win-rate 0.25 --avg-win 3

# Journal - die Quelle mitschreiben ist der entscheidende Teil
python3 run.py paper open --mint <mint> --symbol WIF --price 0.0012 \
    --size 75 --stop 35 --source telegram-gruppe-xy --stage frueh
python3 run.py paper close --id 1 --price 0.0031
python3 run.py paper stats
```

---

## Lagebericht alle paar Stunden

```bash
python3 run.py report --telegram --datei berichte.txt
```

### Was "hyped" hier bedeutet

Wer nach heißen Coins sucht, findet vor allem bezahlte Platzierung -
Börsen-Blogs mit Titeln wie "100x Coins to Watch" verdienen am
Handelsvolumen, nicht an deiner Trefferquote. Das ist Werbung, keine
Recherche.

Messbar ist Hype trotzdem, auf zwei Wegen, die beide auf der Kette stehen:

- **Bezahlte Bewerbung.** Wer einen Boost kauft, bezahlt dafür, dass du
  den Token siehst. Kein Qualitätssignal - aber ein zuverlässiger Hinweis
  darauf, wohin in den nächsten Stunden Retail-Fluss strömt.
- **Umschlag.** Volumen im Verhältnis zur Liquidität zeigt, wo tatsächlich
  Kapital bewegt wird statt nur geredet.

Der Bericht trennt beides von der Frage, ob man den Token anfassen sollte.
Diese beiden Fragen fallen fast nie zusammen - genau darum geht es:

```
-- Am staerksten beworben ----------------------------------------------
 X  MOONPUMP    15/100  blowoff   Liq   120k  1h  +500.0%  Kauf  90%   (1200 Boosts)
    STEADY      65/100  momentum  Liq   120k  1h   +12.0%  Kauf  53%   (400 Boosts)
```

Der meistbeworbene Token ist hier der, der durchfällt. Das ist der
Normalfall, nicht die Ausnahme.

### Alle 3 Stunden automatisch

**Windows** - einmal in PowerShell, dann läuft es dauerhaft:

```powershell
schtasks /create /tn "Memecoin-Lagebericht" /sc hourly /mo 3 /tr "C:\Pfad\zu\memcoin\bericht.bat"
```

Den Pfad anpassen. `bericht.bat` liegt im Ordner und erledigt den Rest.
Prüfen mit `schtasks /query /tn "Memecoin-Lagebericht"`, entfernen mit
`schtasks /delete /tn "Memecoin-Lagebericht" /f`.

**macOS/Linux** - `crontab -e`, dann diese Zeile:

```
17 */3 * * * cd /pfad/zu/memcoin && /usr/bin/python3 run.py report --telegram --datei berichte.txt
```

Minute 17 statt 0 ist Absicht: um Punkt laufen alle Zeitpläne der Welt
gleichzeitig los.

Für Telegram müssen `TELEGRAM_BOT_TOKEN` und `TELEGRAM_CHAT_ID` gesetzt
sein (Menüpunkt 10). Ohne sie erscheint der Bericht nur in der Datei.

### Bericht und Monitor sind nicht dasselbe

| | Bericht | Monitor |
|---|---|---|
| Läuft | alle paar Stunden kurz | dauerhaft |
| Meldet | Lage insgesamt, auch wenn nichts gut ist | nur einzelne Fundstücke |
| Antwortet auf | "was ist gerade los" | "sag mir Bescheid, wenn etwas auffällt" |

Beides parallel ist sinnvoll: der Monitor für den Einzelfall, der Bericht
für den Überblick.

---

## Ankündigungen vor dem Launch

```bash
python3 run.py call add --name "MoonCat Inu" --ticker MCAT \
    --promoter "@cryptoking_calls" --kanal telegram \
    --text "hier den Ankündigungstext einfügen"
```

### Warum das anders funktioniert als alles andere hier

Vor dem Start existiert der Token nicht auf der Blockchain. Keine
Liquidität, kein Mint-Konto, keine Halterverteilung - **damit ist keines
der harten Ausschlusskriterien anwendbar.** Was existiert, sind
ausschliesslich Behauptungen.

Deshalb ist dieser Teil kein Chancenfinder, sondern ein Betrugsdetektor.
Er wird oft "nicht überprüfbar" ausgeben. Das ist das korrekte Ergebnis,
kein Mangel des Werkzeugs.

Prüfbar sind genau drei Dinge:

**1. Der Ankündigungstext.** Manche Formulierungen deuten nicht auf ein
Risiko hin, sie *sind* der Betrug. Die wichtigste: die Aufforderung, vor
dem Start Geld an eine Adresse zu schicken. Es gibt dann noch keinen
Token, den du dafür bekommen könntest - nur ein Versprechen. Wer die
Adresse kontrolliert, kann das Geld behalten, und niemand kann es
zurückholen. Kein weiterer Prüfschritt wiegt das auf.

Weitere Muster mit Gewichtung: garantierte Rendite, Empfehlungssystem
(Schneeballstruktur), behauptete Börsenlistings, Insider-Versprechen,
künstlicher Zeitdruck, Aufforderung zur Privatnachricht, unbelegte
Audit- und Team-Behauptungen.

**2. Ob das Kürzel schon vielfach existiert.** Betrugsfabriken verwenden
dieselben Namen wieder. Ein Kürzel, das bereits dutzendfach vergeben und
fast überall tot ist, ist ein Muster.

**3. Die Bilanz des Promoters.** Das ist der eigentliche Wert - und der
einzige Teil, der Zeit braucht.

### Die Promoter-Bilanz

Jeder erfasste Call wird beim Abgleich automatisch mit dem tatsächlich
gestarteten Token verknüpft, und die vollständige Analyse läuft in dem
Moment, in dem es echte Daten gibt:

```bash
python3 run.py call match        # welche Calls sind inzwischen gestartet
python3 run.py call promoters    # was ist daraus geworden
```

```
  @cryptoking_calls
    14 Calls   9 gestartet   3 nie gestartet   8 beim Start NO-GO
    -> 92% der Calls waren wertlos - dieser Quelle zu folgen kostet Geld
```

Nach zwanzig, dreissig Calls steht dort schwarz auf weiss, ob eine Quelle
dir Geld verdient oder kostet. Das ist überprüfbares Wissen über genau den
Kanal, dem du folgst - und nicht dessen Selbstauskunft.

Bis dahin gilt: **Call erfassen, nicht vorab kaufen, nach dem Start prüfen
lassen.** Dann gibt es echte Daten - und die Bilanz füllt sich nebenbei.

### Nachrichtenlage

Über Google-News-RSS (kostenlos, ohne Schlüssel) wird nach Erwähnungen und
gezielt nach Betrugsmeldungen zum Namen gesucht.

Zur Einordnung: Bei einem frischen Memecoin ist *keine* Berichterstattung
der Normalfall und kein schlechtes Zeichen. Aussagekraft hat nur der
umgekehrte Fall - wenn zu einem angeblich brandneuen Projekt bereits
Betrugsmeldungen existieren.

X/Twitter ist nicht dabei: dafür gibt es seit 2023 keinen kostenlosen
Zugang mehr, und inoffizielle Umgehungen brechen ständig.

---

## Dauerbetrieb: neue Token automatisch verfolgen

```bash
python3 run.py monitor
```

### Warum das kein Launch-Alarm ist

Ein gerade gestarteter Token faellt durch die eigenen Filter dieses Werkzeugs.
Unter zehn Minuten Alter sind Liquiditaet, Kaufverhaeltnis und Umschlag
Rauschen - deshalb steht dort ein Ausschlusskriterium. Ein Alarm im Moment
des Starts waere also eine Meldung ueber etwas, das noch niemand bewerten
kann, dich selbst eingeschlossen.

Der Monitor arbeitet deshalb anders:

1. **Erfassen.** Neue Token wandern auf eine Beobachtungsliste (SQLite,
   uebersteht Neustarts). Es passiert erst einmal nichts.
2. **Reifen lassen.** Jeder Token wird nach Alter gestaffelt nachverfolgt -
   in den ersten Minuten alle 90 Sekunden, spaeter immer seltener. Das
   Anfragebudget bekommt der, bei dem sich noch etwas entscheidet.
3. **Aussortieren.** Wer abgezogene Liquiditaet, keinen Fluss mehr oder zu
   viel Alter zeigt, fliegt von der Liste. Das ist der Regelfall.
4. **Melden.** Alarm gibt es erst, wenn ein Token bewertbar geworden ist,
   **kein** Ausschlusskriterium erfuellt und die Punkteschwelle erreicht.

Der Nebeneffekt ist der eigentliche Gewinn: **du siehst einen Token
frueher als jede Signalgruppe**, weil du nicht darauf wartest, dass jemand
ihn dir schickt - und du siehst ihn *nicht* in der Blowoff-Phase, weil
genau die den Alarm unterdrueckt.

### Zwei Alarmarten

| Art | Wann | Bedeutung |
|---|---|---|
| `FILTER BESTANDEN` | Token wird bewertbar und besteht alle Pruefungen | Kein Kaufsignal - die Erlaubnis, ihn ueberhaupt anzusehen |
| `BLOWOFF - AUSSTIEGSSIGNAL` | Ein bereits gemeldeter Token laeuft senkrecht | Falls du drin bist: hier wird verkauft, nicht nachgekauft |

Jeder Token wird **genau einmal** als Kandidat gemeldet. Kein Dauerfeuer.

### Benachrichtigung per Telegram

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="deine-chat-id"
python3 run.py monitor --telegram --log-file alarme.jsonl
```

Bot anlegen bei **@BotFather**, dann dem eigenen Bot einmal schreiben und die
Chat-ID unter `https://api.telegram.org/bot<TOKEN>/getUpdates` ablesen.

Das ist die sinnvolle Nutzung von Telegram in diesem Zusammenhang: **dein
eigener Kanal, in den nur deine eigene Analyse laeuft** - statt eines Kanals,
in dem dir jemand anderes sagt, was du kaufen sollst.

### Einstellungen

```bash
python3 run.py monitor \
    --min-score 60 \           # strenger melden (Standard 55)
    --discovery-interval 300 \ # Sekunden zwischen Suchlaeufen
    --rpm 50 \                 # Anfragebudget/Min. (API-Limit ca. 60)
    --max-watchlist 400 \      # Obergrenze der Beobachtungsliste
    --log-file alarme.jsonl     # Alarme als JSON-Zeilen mitschreiben
```

`--once` macht genau einen Durchlauf und beendet sich - fuer cron oder die
Windows-Aufgabenplanung.

### Dauerhaft laufen lassen

**Linux/macOS, einfachste Variante** (laeuft weiter, wenn du das Terminal
schliesst):

```bash
nohup python3 run.py monitor --telegram --log-file alarme.jsonl > monitor.log 2>&1 &
```

Beenden mit `pkill -f "run.py monitor"`.

**Linux, sauber als Dienst** (`/etc/systemd/system/memecoin-radar.service`):

```ini
[Unit]
Description=memecoin-radar Monitor
After=network-online.target

[Service]
Type=simple
User=DEIN-BENUTZER
WorkingDirectory=/pfad/zu/memcoin
Environment=TELEGRAM_BOT_TOKEN=123456:ABC...
Environment=TELEGRAM_CHAT_ID=...
ExecStart=/usr/bin/python3 run.py monitor --telegram --log-file alarme.jsonl
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now memecoin-radar
journalctl -u memecoin-radar -f     # mitlesen
```

**Windows:** Aufgabenplanung oeffnen, neue Aufgabe, Trigger "Bei Anmeldung",
Aktion `python` mit den Argumenten `run.py monitor --telegram` und dem
Ordner `memcoin` als Startverzeichnis.

### Was der Monitor nicht kann

- **Er kauft nicht.** Bewusst so. Ein Werkzeug ohne Schluesselmaterial kann
  keine Mittel verlieren, und ein automatischer Einstieg in eine Anlageklasse
  mit dieser Verlustquote ist keine Automatisierung, sondern ein Abfluss.
- **Er ist nicht schneller als Sniper-Bots.** Die kaufen in derselben Sekunde
  wie der Ersteller, ueber direkte Knotenanbindung. Dagegen gewinnst du mit
  Polling nicht - und du willst es auch nicht, denn genau diese Token sind
  die, bei denen die Daten noch Rauschen sind.
- **Er findet keine Gewinner.** Er sortiert Verlierer aus und meldet, was
  uebrig bleibt. Von dem Rest geht der Grossteil trotzdem auf null.
- **Ruhige Tage sind normal.** Wenn tagelang kein Alarm kommt, funktioniert
  der Filter - er findet nichts, weil meistens nichts da ist.

---

## Die Ausschlusskriterien

Jedes einzelne fuehrt zu `NO-GO`, unabhaengig davon, wie gut der Rest aussieht.

| Kriterium | Grenze | Warum |
|---|---|---|
| Liquiditaet | < 15.000 USD | Der Einstieg ist nie das Problem. Der Ausstieg schon. |
| Bewertung / Liquiditaet | > 25x | 5 Mio. "Marktkapitalisierung" auf 50k Liquiditaet sind keine 5 Mio. |
| Alter | < 10 Min. | Keine belastbaren Daten, reines Sniper-Revier. |
| Trades pro Stunde | < 40 | Kein Markt, nur Bots. |
| Umschlag pro Stunde | > 15x Liquiditaet | Wash-Trading fuers Ranking. |
| Kaufanteil | > 88% | Eine Kampagne baut ihre Gegenseite auf. Du waerst die Gegenseite. |
| Kaufanteil | < 30% | Der Ausstieg laeuft bereits. |
| Mint-Authority aktiv | - | Der Ersteller kann dich jederzeit auf null verwaessern. |
| Freeze-Authority aktiv | - | Dein Wallet kann eingefroren werden. Du kaufst etwas, das du nicht verkaufen kannst. |
| LP gesperrt | < 50% | Die Liquiditaet kann in einer Transaktion abgezogen werden. |
| Groesster Halter | > 25% | Eine einzige Verkaufsorder beendet den Token. |

Dass beim `scan` regelmaessig 80-90% der Kandidaten ausscheiden, ist das
erwartete Ergebnis und kein Fehler des Filters.

## Die Phasen

| Phase | Bedeutung |
|---|---|
| `FRUEH` | Jung, Fluss baut sich auf. Hoechste Chance, hoechstes Rugrisiko. |
| `MOMENTUM` | Laeuft geordnet, Kaeufer und Verkaeufer im Gleichgewicht. |
| `BLOWOFF` | Senkrechte Kerze bei einseitigem Kaufdruck. **Hier posten Signalgruppen.** |
| `NACH_DUMP` | Der Ausstieg ist gelaufen. "Guenstig" heisst nur: billiger als der Betrug. |
| `TOT` | Kein Fluss mehr. |

---

## Zu Signalgruppen und "Insider"-Coins

Die haeufigste Frage zu diesem Thema lautet, wie man an Insider-Informationen
oder an die guten Telegram-Gruppen kommt. Die ehrliche Antwort:

**In einer bezahlten Signalgruppe bist du nicht der Insider. Du bist das
Produkt.** Das Geschaeftsmodell ist strukturell immer dasselbe:

1. Die Betreiber (und ein innerer Kreis) kaufen zuerst, oft ueber mehrere
   Wallets verteilt, um die Halterverteilung unauffaellig aussehen zu lassen.
2. Das Signal geht an die Gruppe. Je groesser die Gruppe, desto verlaesslicher
   die Bewegung - und desto praeziser planbar der Ausstieg.
3. Der Kaufdruck der Mitglieder ist die Liquiditaet, gegen die der innere
   Kreis verkauft. Genau das misst dieses Werkzeug als Kaufanteil > 88%.
4. Was uebrig bleibt, faellt zurueck. Die Gewinnmeldungen in der Gruppe
   stammen von Schritt 1, nicht von Schritt 3.

Das ist kein moralisches Argument, sondern ein mechanisches: **eine Gruppe
mit 40.000 Mitgliedern kann keinen Vorteil verteilen, weil die Mitglieder
selbst die Bewegung sind, auf die sie wetten.** Ein Vorteil, den alle kennen,
ist keiner mehr. Je groesser die Gruppe, desto sicherer verlierst du.

Dazu kommt: koordiniertes Pumpen mit anschliessendem Abverkauf an die eigene
Zielgruppe ist in der EU (MAR/MiCA), in Oesterreich und in den meisten anderen
Jurisdiktionen Marktmanipulation. Das Risiko traegt nicht nur der Organisator,
sondern potenziell auch, wer nachweislich koordiniert mitmacht.

### Was stattdessen tatsaechlich ein Vorteil ist

Ein echter Informationsvorsprung im Memecoin-Handel kommt nicht aus Gruppen,
sondern aus Daten, die oeffentlich, aber unbequem auszuwerten sind:

- **On-Chain-Daten in Echtzeit.** Jede Wallet, jeder Pool, jede Sperre ist
  oeffentlich einsehbar. Die meisten schauen nicht hin. Genau das automatisiert
  dieses Werkzeug.
- **Wallet-Verfolgung.** Adressen, die ueber Monate nachweislich profitabel
  waren, sind auf der Kette identifizierbar (Solscan, Birdeye, GMGN, Cielo).
  Ihre Kaeufe zu sehen ist legal und tatsaechlich frueh - ihnen blind zu
  folgen dagegen nicht, weil du ihre Ausstiege nicht mitbekommst.
- **Sperrfristen und Freischaltungen.** Oeffentlich dokumentiert, aber selten
  eingepreist.
- **Konsequente Ausfuehrung.** Der langweiligste und wirksamste Punkt: Stops
  einhalten, Positionsgroessen begrenzen, Journal fuehren. Das schlaegt jede
  Signalgruppe, weil es nicht davon abhaengt, recht zu haben.

Zur Rolle von X und Telegram: nuetzlich sind sie als **Beobachtungsposten**,
nicht als Signalquelle. Wo eine Erzaehlung entsteht, bevor sie im Preis steht,
ist eine echte Information. Was in einem Kanal mit Kaufempfehlung und
Kursziel gepostet wird, ist keine.

### Die einzige Kennzahl, die zaehlt

`paper stats` wertet deine Ergebnisse nach Quelle aus:

```
-- Ergebnis nach Quelle ------------------------------------------------
  eigener-scan           2 Trades   +3.50R im Schnitt
  telegram-gruppe        2 Trades   -1.00R im Schnitt
```

Wenn du bei jedem Trade `--source` mitschreibst, beantwortet dir das nach
dreissig Trades faktisch, welche Signalquelle dir Geld verdient und welche
dich Geld kostet. Das ist ueberpruefbares Wissen ueber deinen eigenen Handel -
und damit mehr, als jede Gruppe dir verkaufen kann.

---

## Zahlen, die man einmal gesehen haben sollte

`python3 run.py math` rechnet das durch. Der Kern, bei 25% Trefferquote und
3R Durchschnittsgewinn - also einer **positiven** Strategie:

```
    1.0% pro Trade:    0.5% Ruinrisiko
    2.0% pro Trade:   17.0%
    5.0% pro Trade:   72.9%  #############################
   10.0% pro Trade:   94.1%  #####################################
   25.0% pro Trade:  100.0%  #######################################
```

Gleiche Strategie, gleicher Vorteil. Nur die Positionsgroesse entscheidet
ueber Ruin oder Ueberleben. Deshalb ist die Voreinstellung 1,5% pro Trade -
und deshalb warnt das Werkzeug, wenn du darueber gehst.

## Aufbau

```
.
  run.py       Einstiegspunkt
radar/
  config.py    Schwellenwerte und Tunables (per JSON ueberschreibbar)
  sources.py   HTTP-Clients: DexScreener, RugCheck (defensiv geparst)
  model.py     Normalisierte Momentaufnahme eines Handelspaares
  scoring.py   Ausschlusskriterien, Punktebewertung, Phasenerkennung
  risk.py      Positionsgroesse, Preiseinfluss (x*y=k), Erwartungswert, Ruinrisiko
  journal.py   SQLite-Handelsjournal mit Auswertung
  monitor.py   Dauerbetrieb: Beobachtungsliste, Reifeplanung, Anfragebudget
  notify.py    Benachrichtigungskanaele (Konsole, Datei, Telegram)
  onchain.py   Direkte Blockchain-Abfrage ueber einen Solana-RPC-Knoten
  menu.py      Menuegefuehrte Bedienung
  wizard.py    Gefuehrte Einrichtung mit Verbindungstest
  env_file.py  Laedt und speichert Zugangsdaten in .env
  prelaunch.py Call-Register, Betrugsmuster im Text, Promoter-Bilanz
  dossier.py   Pre-Launch-Dossier und dessen Darstellung
  news.py      Nachrichtenlage ueber Google-News-RSS
  digest.py    Periodischer Lagebericht
  report.py    Textausgabe
  cli.py       Kommandozeile
tests/         161 Tests: python3 -m unittest discover -s tests
```

Eigene Schwellenwerte:

```bash
python3 run.py --config meine-config.json check <mint>
```

## Datenquellen

- [DexScreener API](https://docs.dexscreener.com/api/reference) - Preis,
  Liquiditaet, Volumen, Transaktionsfluss. Oeffentlich, kein Schluessel,
  ca. 60 Anfragen/Minute.
- [RugCheck API](https://api.rugcheck.xyz/swagger/index.html) - Mint-/Freeze-
  Authority, LP-Sperre, Halterverteilung, Insider-Netzwerke.

Beide Schemata aendern sich gelegentlich. Alle Parser sind deshalb defensiv:
ein fehlendes oder falsch typisiertes Feld darf nie einen Scan abbrechen.

## Grenzen

- **Die Daten sind nachlaufend.** DexScreener aggregiert; in einem 30 Sekunden
  alten Pool sind die Kennzahlen bedeutungslos.
- **Der Preiseinfluss ist eine Naeherung** (Constant-Product ohne Gebuehren und
  ohne Routing ueber mehrere Pools). Fuer die Groessenordnung reicht sie - und
  die Groessenordnung ist genau das, was die meisten ignorieren.
- **Kein Filter erkennt jeden Rug.** Ein Deployer, der ueber fuenfzig Wallets
  verteilt, faellt durch die Halterpruefung. Die Filter senken die
  Wahrscheinlichkeit, sie eliminieren sie nicht.
- **Ein sauberer Bericht ist kein Kaufsignal.** Er bedeutet nur: die bekannten
  K.-o.-Kriterien liegen nicht vor. Auch ein technisch einwandfreier Memecoin
  geht meistens auf null.

---

Analysewerkzeug, keine Anlageberatung. Handle nur mit Kapital, dessen
vollstaendigen Verlust du einkalkuliert hast.
