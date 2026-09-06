"""Nachrichtenlage zu einem Projektnamen - ueber Google-News-RSS.

Kostenlos, ohne Schluessel, maschinenlesbar. Deckt Krypto-Medien gut ab,
X-Beitraege dagegen nicht - dafuer gibt es seit 2023 keinen kostenlosen
Zugang mehr.

Wichtig fuer die Auswertung: Bei einem frischen Memecoin ist *keine*
Berichterstattung der Normalfall und kein schlechtes Zeichen. Aussagekraft
hat nur der umgekehrte Fall - wenn zu einem angeblich brandneuen Projekt
bereits Betrugsmeldungen existieren.
"""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .sources import HttpClient, SourceError

BASIS = "https://news.google.com/rss/search"

# Begriffe, die eine Meldung als Warnung statt als Berichterstattung ausweisen.
WARNBEGRIFFE = re.compile(
    r"\b(scam|rug|rugpull|rug pull|honeypot|fraud|betrug|abzocke|"
    r"exit scam|ponzi|lawsuit|klage|warnung|warning|stolen|gestohlen|"
    r"hack|exploit|drainer)\b",
    re.IGNORECASE,
)


@dataclass
class Meldung:
    titel: str
    link: str
    quelle: str
    datum: str

    @property
    def ist_warnung(self) -> bool:
        return bool(WARNBEGRIFFE.search(self.titel))


def parse_rss(xml_text: str, limit: int = 10) -> list[Meldung]:
    """Liest Google-News-RSS. Fehlerhafte Eintraege werden uebergangen."""
    try:
        wurzel = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    meldungen: list[Meldung] = []
    for item in wurzel.iter("item"):
        titel = (item.findtext("title") or "").strip()
        if not titel:
            continue
        quelle = (item.findtext("source") or "").strip()
        meldungen.append(Meldung(
            titel=titel,
            link=(item.findtext("link") or "").strip(),
            quelle=quelle or "unbekannt",
            datum=(item.findtext("pubDate") or "").strip(),
        ))
        if len(meldungen) >= limit:
            break
    return meldungen


class News:
    def __init__(self, client: HttpClient | None = None, sprache: str = "de") -> None:
        self.client = client or HttpClient(timeout=15.0, min_interval=1.0)
        self.sprache = sprache

    def _abfrage(self, query: str, limit: int) -> list[Meldung]:
        land = "DE" if self.sprache == "de" else "US"
        url = (f"{BASIS}?q={urllib.parse.quote(query)}"
               f"&hl={self.sprache}&gl={land}&ceid={land}:{self.sprache}")
        try:
            return parse_rss(self.client.get_text(url), limit)
        except SourceError:
            return []

    def erwaehnungen(self, name: str, limit: int = 8) -> list[Meldung]:
        """Allgemeine Berichterstattung zum Namen."""
        return self._abfrage(f'"{name}" crypto', limit)

    def warnungen(self, name: str, limit: int = 8) -> list[Meldung]:
        """Gezielt nach Betrugsmeldungen suchen."""
        treffer = self._abfrage(f'"{name}" (scam OR rug OR fraud OR betrug)', limit)
        # Die Abfrage findet auch Unverfaengliches - nur echte Warnungen behalten.
        return [m for m in treffer if m.ist_warnung]
