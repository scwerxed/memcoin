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

## Installation

```bash
git clone https://github.com/scwerxed/memcoin.git
cd memcoin
python3 run.py demo        # Beispielausgabe, ohne Netzwerkzugriff
```

Unter Windows heisst der Befehl in der Regel `python` statt `python3`.
Benoetigt wird Python 3.11 oder neuer.

Optional, fuer die vollstaendige Vertragspruefung (Mint-/Freeze-Authority,
LP-Lock, Halterverteilung) einen kostenlosen RugCheck-Schluessel setzen:

```bash
export RUGCHECK_API_KEY="dein-key"
```

Ohne diesen Schluessel laeuft alles weiter, aber die Bewertung wird bei 65/100
gedeckelt - ohne Vertragspruefung fehlen genau die Angaben, an denen ein Rug
erkennbar waere.

## Befehle

| Befehl | Zweck |
|---|---|
| `check <mint>` | Einzelnen Token vollstaendig pruefen |
| `scan` | Neue und beworbene Token durchsuchen und filtern |
| `size` | Positionsgroesse und Preiseinfluss berechnen |
| `math` | Erwartungswert und Ruinrisiko durchrechnen |
| `paper` | Handelsjournal fuehren und auswerten |
| `monitor` | **Dauerbetrieb:** neue Token erfassen, reifen lassen, bei Eignung melden |
| `watch <mint>` | Einzelnen Token beobachten, Phasenwechsel melden |
| `demo` | Beispielausgabe ohne Netzwerk |

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
  report.py    Textausgabe
  cli.py       Kommandozeile
tests/         62 Tests: python3 -m unittest discover -s tests
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
