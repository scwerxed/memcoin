"""Menuegefuehrte Bedienung.

Fuer alle, die sich keine Befehlszeilen merken wollen - also fuer die
meisten. Jeder Punkt baut im Hintergrund denselben Aufruf zusammen, den
man auch von Hand tippen koennte, und zeigt ihn an. Wer mag, lernt die
Befehle so nebenbei; wer nicht, muss es nie.
"""

from __future__ import annotations

import os
from typing import Callable

from . import env_file

KOPF = r"""
========================================================================
  memecoin-radar
  Analysewerkzeug. Kein Kaufsignal, keine Anlageberatung.
========================================================================
"""

PUNKTE = [
    ("1", "Ankündigung prüfen  - jemand kündigt einen Coin VOR dem Launch an"),
    ("2", "Calls verwalten     - Liste, Promoter-Bilanz, Abgleich mit Launches"),
    ("3", "Token prüfen        - der Coin ist schon gestartet"),
    ("4", "Markt durchsuchen   - was besteht gerade die Filter"),
    ("5", "Monitor starten     - läuft dauerhaft, meldet Fundstücke"),
    ("6", "Positionsgröße      - wie viel darf ich setzen"),
    ("7", "Meine Trades        - Journal und Auswertung"),
    ("8", "Beispiel ansehen    - Ausgabe ohne Internet"),
    ("9", "Einrichtung         - Zugänge eintragen und testen"),
    ("0", "Beenden"),
]


def _eingabe(text: str, standard: str = "") -> str:
    hinweis = f" [{standard}]" if standard else ""
    try:
        wert = input(f"  {text}{hinweis}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""
    return wert or standard


def _zahl(text: str, standard: float) -> float:
    while True:
        roh = _eingabe(text, str(standard))
        if not roh:
            return standard
        try:
            return float(roh.replace(",", "."))
        except ValueError:
            print("  Bitte eine Zahl eingeben, z. B. 5000")


def _mehrzeilig(text: str) -> str:
    """Liest mehrere Zeilen bis zu einer Leerzeile.

    Ankuendigungen sind fast immer mehrzeilig - eine einzelne input()-Zeile
    wuerde den Text abschneiden und genau die Muster verlieren, um die es geht.
    """
    print(f"  {text}")
    print("  (einfügen, dann Enter auf einer leeren Zeile)")
    zeilen: list[str] = []
    while True:
        try:
            zeile = input("  | ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not zeile.strip():
            break
        zeilen.append(zeile)
    return "\n".join(zeilen)


def _status() -> str:
    """Kurze Zustandszeile - was ist eingerichtet, was fehlt."""
    teile = []
    teile.append("Blockchain: " + ("eigener Knoten" if os.environ.get("SOLANA_RPC_URL")
                                   else "öffentlich (langsam)"))
    teile.append("Vertragsprüfung: " + ("Schlüssel" if os.environ.get("RUGCHECK_API_KEY")
                                        else "ohne Schlüssel"))
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        teile.append("Telegram: an")
    return "  " + "   |   ".join(teile)


def _zeige_befehl(argv: list[str]) -> None:
    print()
    print("  Entspricht dem Befehl:")
    print("    python run.py " + " ".join(argv))
    print()


def run_menu(dispatch: Callable[[list[str]], int]) -> int:
    """Hauptschleife. `dispatch` fuehrt eine Argumentliste aus."""
    print(KOPF)
    if not os.path.isfile(env_file.ENV_DATEI):
        print("  Noch nichts eingerichtet. Punkt 9 macht das in zwei Minuten -")
        print("  du kannst aber auch sofort loslegen, es geht auch ohne.")
        print()

    while True:
        print("-" * 72)
        print(_status())
        print("-" * 72)
        for taste, text in PUNKTE:
            print(f"   {taste}   {text}")
        print()

        wahl = _eingabe("Auswahl")
        print()

        if wahl in ("0", "q", "quit", "exit", ""):
            print("  Bis dann.")
            return 0

        argv = _baue_aufruf(wahl)
        if argv is None:
            print("  Unbekannte Auswahl. Bitte eine Zahl aus der Liste.")
            print()
            continue

        _zeige_befehl(argv)
        try:
            dispatch(argv)
        except KeyboardInterrupt:
            print("\n  Abgebrochen.")
        except SystemExit:
            pass
        except Exception as exc:  # Ein Fehler darf nie das Menue beenden
            print(f"  Fehler: {exc}")

        print()
        _eingabe("Weiter mit Enter")
        print()


def _baue_aufruf(wahl: str) -> list[str] | None:
    """Uebersetzt eine Menueauswahl in Befehlszeilenargumente."""
    if wahl == "1":
        name = _eingabe("Name des Projekts")
        promoter = _eingabe("Wer kündigt es an? (Handle oder Kanalname)")
        if not name or not promoter:
            print("  Name und Ankündiger werden beide gebraucht.")
            return None
        argv = ["call", "add", "--name", name, "--promoter", promoter]
        ticker = _eingabe("Kürzel, z. B. MCAT (leer = keins)")
        if ticker:
            argv += ["--ticker", ticker]
        kanal = _eingabe("Wo angekündigt?", "telegram")
        if kanal:
            argv += ["--kanal", kanal]
        text = _mehrzeilig("Ankündigungstext einfügen:")
        if text:
            argv += ["--text", text]
        return argv

    if wahl == "2":
        return _call_menue()

    if wahl == "3":
        mint = _eingabe("Token-Adresse (Mint)")
        if not mint:
            return None
        argv = ["check", mint]
        kapital = _eingabe("Dein Gesamtkapital in USD (leer = keine Positionsplanung)")
        if kapital:
            try:
                argv += ["--bankroll", str(float(kapital.replace(",", ".")))]
            except ValueError:
                pass
        return argv

    if wahl == "4":
        nur = _eingabe("Nur was die Filter besteht? (j/n)", "j")
        argv = ["scan", "--limit", "25"]
        if nur.lower().startswith("j"):
            argv.append("--only-passing")
        return argv

    if wahl == "5":
        argv = ["monitor"]
        if os.environ.get("TELEGRAM_BOT_TOKEN"):
            if _eingabe("Meldungen auch per Telegram? (j/n)", "j").lower().startswith("j"):
                argv.append("--telegram")
        argv += ["--log-file", "alarme.jsonl"]
        return argv

    if wahl == "6":
        argv = ["size", "--bankroll", str(_zahl("Dein Gesamtkapital in USD", 1000))]
        mint = _eingabe("Token-Adresse (leer = Liquidität von Hand eingeben)")
        if mint:
            argv += ["--mint", mint]
        else:
            argv += ["--liquidity", str(_zahl("Liquidität des Pools in USD", 50000))]
        argv += ["--risk", str(_zahl("Risiko pro Trade in Prozent", 1.5))]
        argv += ["--stop", str(_zahl("Stop in Prozent", 35))]
        return argv

    if wahl == "7":
        return _journal_menue()

    if wahl == "8":
        return ["demo"]

    if wahl == "9":
        return ["setup"]

    return None


def _call_menue() -> list[str] | None:
    print("   a   Bilanz der Promoter    - wer kostet dich Geld")
    print("   b   Alle Calls auflisten")
    print("   c   Nur offene Calls       - noch nicht gestartet")
    print("   d   Abgleich starten       - welche Calls sind inzwischen gestartet")
    print()
    wahl = _eingabe("Auswahl", "a").lower()
    if wahl == "a":
        return ["call", "promoters"]
    if wahl == "b":
        return ["call", "list"]
    if wahl == "c":
        return ["call", "list", "--open-only"]
    if wahl == "d":
        return ["call", "match"]
    return None


def _journal_menue() -> list[str] | None:
    print("   a   Auswertung ansehen")
    print("   b   Trade eintragen")
    print("   c   Trade abschließen")
    print("   d   Alle Trades auflisten")
    print()
    wahl = _eingabe("Auswahl", "a").lower()

    if wahl == "a":
        return ["paper", "stats"]
    if wahl == "d":
        return ["paper", "list"]
    if wahl == "b":
        mint = _eingabe("Token-Adresse")
        symbol = _eingabe("Kürzel, z. B. WIF")
        if not mint or not symbol:
            return None
        return [
            "paper", "open", "--mint", mint, "--symbol", symbol,
            "--price", str(_zahl("Einstiegspreis", 0.0)),
            "--size", str(_zahl("Positionsgröße in USD", 0.0)),
            "--stop", str(_zahl("Stop in Prozent", 35)),
            "--source", _eingabe("Woher kam das Signal?", "eigener-scan"),
        ]
    if wahl == "c":
        nummer = _eingabe("Nummer des Trades (steht in der Liste)")
        if not nummer.isdigit():
            return None
        return ["paper", "close", "--id", nummer,
                "--price", str(_zahl("Ausstiegspreis", 0.0))]
    return None
