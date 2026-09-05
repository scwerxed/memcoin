"""Gefuehrte Einrichtung.

Fragt die Zugangsdaten nacheinander ab, prueft jede einzelne sofort gegen
den echten Dienst und schreibt sie in eine lokale Datei. Damit entfaellt
das Hantieren mit Umgebungsvariablen vollstaendig.
"""

from __future__ import annotations

import os

from . import env_file
from .config import Settings
from .onchain import PUBLIC_RPC, SolanaRpc
from .sources import DexScreener, HttpClient, RugCheck, SourceError

# Wrapped SOL - existiert immer und eignet sich deshalb als Testabfrage.
TEST_MINT = "So11111111111111111111111111111111111111112"

OK = "  [OK]   "
FEHLER = "  [!]    "
INFO = "  ->     "


def _frage(text: str, aktuell: str | None = None) -> str | None:
    """Eine Eingabe. Leer lassen behaelt den bisherigen Wert."""
    if aktuell:
        print(f"    Bisher: {env_file.masked(aktuell)}")
        print("    Leer lassen = behalten,  '-' = loeschen")
    try:
        eingabe = input(f"    {text}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return aktuell
    if not eingabe:
        return aktuell
    if eingabe == "-":
        return None
    return eingabe


def _teste_dexscreener() -> bool:
    print("    Prüfe Marktdaten (DexScreener) ...")
    try:
        paare = DexScreener(HttpClient(15.0, 0.2)).pairs_for_token(TEST_MINT)
    except SourceError as exc:
        print(FEHLER + f"nicht erreichbar: {exc}")
        return False
    if not paare:
        print(FEHLER + "keine Daten erhalten - moeglicherweise blockiert dein Netzwerk den Zugriff")
        return False
    print(OK + f"erreichbar ({len(paare)} Handelspaare für den Testtoken)")
    return True


def _teste_rpc(url: str | None) -> bool:
    ziel = url or PUBLIC_RPC
    name = "dein Knoten" if url else "der öffentliche Knoten"
    print(f"    Prüfe Blockchain-Zugang ({name}) ...")
    try:
        info = SolanaRpc(ziel, HttpClient(20.0, 0.2)).mint_info(TEST_MINT)
    except SourceError as exc:
        print(FEHLER + str(exc))
        return False
    if not info:
        print(FEHLER + "Antwort unbrauchbar - Adresse prüfen")
        return False
    print(OK + "funktioniert")
    return True


def _teste_rugcheck(key: str | None, base: str | None) -> bool:
    print("    Prüfe Vertragsprüfung (RugCheck) ...")
    intervall = 1.1 if key else 6.5
    rug = RugCheck(HttpClient(20.0, intervall), key, base)
    try:
        bericht = rug.report(TEST_MINT)
    except SourceError as exc:
        print(FEHLER + str(exc))
        return False
    if not bericht:
        print(FEHLER + "keine Antwort" + (" - Schlüssel prüfen" if key else ""))
        return False
    print(OK + ("funktioniert (60 Abfragen/Minute)" if key
                else "funktioniert ohne Schlüssel (10 Abfragen/Minute)"))
    return True


def run_setup(settings: Settings | None = None) -> int:
    settings = settings or Settings()
    werte: dict[str, str] = {}
    for name in env_file.BEKANNTE_SCHLUESSEL:
        vorhanden = os.environ.get(name)
        if vorhanden:
            werte[name] = vorhanden

    print()
    print("=" * 68)
    print(" Einrichtung")
    print("=" * 68)
    print()
    print(" Alle Angaben sind freiwillig. Ohne sie funktioniert das Werkzeug")
    print(" auch - nur langsamer und mit weniger Prüfungen. Du kannst jede")
    print(" Frage mit Enter überspringen und später zurückkommen.")
    print()
    print(" Keine dieser Angaben kann Geld bewegen. Es sind reine Lese-")
    print(" zugänge. Nach einer Seed-Phrase oder einem privaten Schlüssel")
    print(" wird hier nie gefragt - wer das tut, will dich bestehlen.")
    print()

    # --- 1. Marktdaten ------------------------------------------------ #
    print("-" * 68)
    print(" 1/4  Marktdaten")
    print("-" * 68)
    print(INFO + "Braucht nichts. Wird nur getestet.")
    _teste_dexscreener()
    print()

    # --- 2. Blockchain-Knoten ----------------------------------------- #
    print("-" * 68)
    print(" 2/4  Blockchain-Zugang  (empfohlen, kostenlos)")
    print("-" * 68)
    print(INFO + "Damit liest das Werkzeug direkt aus der Blockchain, ob der")
    print("         Ersteller noch Token nachdrucken oder dein Wallet einfrieren")
    print("         kann. Kostenlos bei fluxrpc.com, helius.dev oder quicknode.com.")
    print(INFO + "Es ist die lange Adresse, die dort als 'RPC' oder 'HTTP' steht,")
    print("         z. B.  https://eu.fluxrpc.com?key=...")
    print()
    werte["SOLANA_RPC_URL"] = _frage("Adresse", werte.get("SOLANA_RPC_URL")) or ""
    if not werte["SOLANA_RPC_URL"]:
        werte.pop("SOLANA_RPC_URL", None)
        print(INFO + "Übersprungen - es wird der öffentliche Knoten benutzt.")
    _teste_rpc(werte.get("SOLANA_RPC_URL"))
    print()

    # --- 3. RugCheck --------------------------------------------------- #
    print("-" * 68)
    print(" 3/4  Vertragsprüfung  (optional)")
    print("-" * 68)
    print(INFO + "Prüft zusätzlich, ob die Liquidität gesperrt ist und wie die")
    print("         Token verteilt sind - die zwei häufigsten Betrugsmuster.")
    print(INFO + "Funktioniert ohne Schlüssel, dann mit 10 statt 60 Abfragen")
    print("         pro Minute. Schlüssel gibt es auf rugcheck.xyz oder fluxrpc.com.")
    print()
    werte["RUGCHECK_API_KEY"] = _frage("Schlüssel", werte.get("RUGCHECK_API_KEY")) or ""
    if not werte["RUGCHECK_API_KEY"]:
        werte.pop("RUGCHECK_API_KEY", None)
    if werte.get("RUGCHECK_API_KEY"):
        print()
        print(INFO + "Falls dein Anbieter eine eigene Adresse nennt ('API ENDPOINT'),")
        print("         hier eintragen. Sonst einfach Enter drücken.")
        werte["RUGCHECK_BASE_URL"] = _frage("Adresse", werte.get("RUGCHECK_BASE_URL")) or ""
        if not werte["RUGCHECK_BASE_URL"]:
            werte.pop("RUGCHECK_BASE_URL", None)
    _teste_rugcheck(werte.get("RUGCHECK_API_KEY"), werte.get("RUGCHECK_BASE_URL"))
    print()

    # --- 4. Telegram --------------------------------------------------- #
    print("-" * 68)
    print(" 4/4  Telegram-Benachrichtigung  (optional)")
    print("-" * 68)
    print(INFO + "Nur nötig, wenn der Monitor dir aufs Handy melden soll.")
    print(INFO + "Bot anlegen: in Telegram @BotFather schreiben, /newbot.")
    print("         Chat-ID: dem eigenen Bot einmal schreiben, dann")
    print("         api.telegram.org/bot<TOKEN>/getUpdates im Browser öffnen.")
    print()
    werte["TELEGRAM_BOT_TOKEN"] = _frage("Bot-Token", werte.get("TELEGRAM_BOT_TOKEN")) or ""
    if not werte["TELEGRAM_BOT_TOKEN"]:
        werte.pop("TELEGRAM_BOT_TOKEN", None)
    else:
        werte["TELEGRAM_CHAT_ID"] = _frage("Chat-ID", werte.get("TELEGRAM_CHAT_ID")) or ""
        if not werte["TELEGRAM_CHAT_ID"]:
            werte.pop("TELEGRAM_CHAT_ID", None)
    print()

    # --- Speichern ----------------------------------------------------- #
    datei = env_file.save(werte)
    for name, wert in werte.items():
        os.environ[name] = wert

    print("=" * 68)
    print(f" Gespeichert in {datei.resolve()}")
    print("=" * 68)
    print()
    for name in env_file.BEKANNTE_SCHLUESSEL:
        zustand = env_file.masked(werte.get(name))
        print(f"   {name:<20} {zustand}")
    print()
    print(" Diese Datei enthält Geheimnisse. Sie steht in .gitignore und")
    print(" landet deshalb nicht auf GitHub - aber gib sie auch sonst nicht")
    print(" weiter und schick keine Screenshots davon.")
    print()
    print(" Fertig. Beim nächsten Start wird alles automatisch geladen.")
    print()
    return 0
