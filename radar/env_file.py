"""Laedt Zugangsdaten aus einer lokalen .env-Datei.

Damit entfaellt das Setzen von Umgebungsvariablen von Hand - der haeufigste
Grund, warum eine Einrichtung scheitert. Die Datei wird nie eingecheckt.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATEI = ".env"

# Nur diese Namen werden gelesen und geschrieben. Eine .env-Datei ist ein
# beliebter Ort fuer allerlei Geheimnisse - hier wird nur uebernommen, was
# dieses Werkzeug tatsaechlich braucht.
BEKANNTE_SCHLUESSEL = (
    "SOLANA_RPC_URL",
    "RUGCHECK_API_KEY",
    "RUGCHECK_BASE_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)


def parse(text: str) -> dict[str, str]:
    """Liest KEY=VALUE-Zeilen. Kommentare und Leerzeilen werden uebergangen."""
    werte: dict[str, str] = {}
    for zeile in text.splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, _, wert = zeile.partition("=")
        name = name.strip()
        wert = wert.strip()
        # Anfuehrungszeichen entfernen - die schreiben viele aus Gewohnheit dazu
        if len(wert) >= 2 and wert[0] == wert[-1] and wert[0] in "\"'":
            wert = wert[1:-1]
        if name in BEKANNTE_SCHLUESSEL and wert:
            werte[name] = wert
    return werte


def load(pfad: str | Path = ENV_DATEI) -> dict[str, str]:
    """Uebertraegt die Datei in die Umgebung.

    Bereits gesetzte Variablen haben Vorrang - wer sie bewusst im Terminal
    setzt, will nicht von einer Datei ueberstimmt werden.
    """
    datei = Path(pfad)
    if not datei.is_file():
        return {}
    try:
        werte = parse(datei.read_text(encoding="utf-8"))
    except OSError:
        return {}

    uebernommen = {}
    for name, wert in werte.items():
        if not os.environ.get(name):
            os.environ[name] = wert
            uebernommen[name] = wert
    return uebernommen


def save(werte: dict[str, str], pfad: str | Path = ENV_DATEI) -> Path:
    """Schreibt die Datei und schraenkt die Zugriffsrechte ein, wo moeglich."""
    datei = Path(pfad)
    zeilen = [
        "# Zugangsdaten fuer memecoin-radar.",
        "# Diese Datei enthaelt Geheimnisse - nicht weitergeben, nicht einchecken.",
        "# Sie steht in .gitignore und landet deshalb nicht auf GitHub.",
        "",
    ]
    for name in BEKANNTE_SCHLUESSEL:
        wert = werte.get(name)
        if wert:
            zeilen.append(f"{name}={wert}")
    datei.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    try:
        os.chmod(datei, 0o600)  # unter Windows weitgehend wirkungslos, schadet aber nicht
    except OSError:
        pass
    return datei


def masked(wert: str | None) -> str:
    """Gekuerzte Darstellung fuer die Anzeige - nie der vollstaendige Wert."""
    if not wert:
        return "(nicht gesetzt)"
    if len(wert) <= 10:
        return wert[:2] + "…"
    return f"{wert[:6]}…{wert[-4:]}"
