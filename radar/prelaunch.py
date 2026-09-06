"""Pre-Launch-Calls erfassen, pruefen und die Promoter danach bewerten.

Vor dem Start eines Memecoins gibt es keine On-Chain-Daten: keine
Liquiditaet, kein Mint-Konto, keine Halter. Damit ist keines der harten
Ausschlusskriterien anwendbar. Pruefbar ist genau dreierlei:

  1. Der Text der Ankuendigung selbst. Bestimmte Formulierungen sind keine
     Warnzeichen, sondern der Betrug - allen voran die Aufforderung, vor
     dem Start Geld an eine Adresse zu schicken.
  2. Ob Name und Kuerzel bereits vielfach existieren. Betrugsfabriken
     verwenden dieselben Namen wieder.
  3. Was aus den frueheren Calls desselben Promoters geworden ist.

Punkt 3 ist der eigentliche Wert und braucht Zeit: erst nach zwanzig,
dreissig erfassten Calls steht da eine belastbare Bilanz. Sie ist dann
aber ueberpruefbares Wissen ueber genau die Quelle, der du folgst - und
nicht die Selbstauskunft eines Kanals.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    ticker        TEXT,
    promoter      TEXT NOT NULL,
    kanal         TEXT,
    erfasst_am    INTEGER NOT NULL,
    start_geplant TEXT,
    promo_text    TEXT,
    presale_adresse TEXT,
    notiz         TEXT,
    status        TEXT NOT NULL DEFAULT 'offen',
    mint          TEXT,
    verknuepft_am INTEGER,
    score_beim_start INTEGER,
    phase_beim_start TEXT,
    liquiditaet_beim_start REAL,
    ausschluss_beim_start INTEGER
);
CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status);
CREATE INDEX IF NOT EXISTS idx_calls_promoter ON calls(promoter);
"""


# --------------------------------------------------------------------- #
# Textmuster. Jede Regel: Muster, Gewicht, Erklaerung.
# Gewicht 100 = allein schon vernichtend.
# --------------------------------------------------------------------- #
@dataclass(frozen=True)
class Regel:
    muster: str
    gewicht: int
    erklaerung: str


REGELN: tuple[Regel, ...] = (
    Regel(
        r"\b(send|schick|sende|senden|transfer|ueberweis|überweis)\b"
        # Punkt nur zwischen Ziffern zulassen: Betragsangaben wie "0.5 SOL"
        # enthalten einen Punkt, Satzgrenzen sollen aber trennen.
        r"(?:[^.!?\n]|\.(?=\d)){0,60}"
        r"\b(sol|eth|bnb|usdt|usdc|geld|funds)\b",
        100,
        "Aufforderung, vor dem Start Geld zu schicken. Es gibt noch keinen "
        "Token, den du dafuer bekommen koenntest - nur ein Versprechen. Wer "
        "die Adresse kontrolliert, kann das Geld behalten, und niemand kann "
        "es zurueckholen. Das ist kein Warnzeichen, das ist der Betrug",
    ),
    Regel(
        r"\b(presale|pre-sale|vorverkauf|private sale|seed round)\b"
        r"(?:[^.\n]|\.(?=\d)){0,40}"
        r"\b(wallet|adresse|address)\b",
        100,
        "Presale-Adresse genannt. Siehe oben: ohne Token auf der Kette gibt es "
        "keinerlei Absicherung",
    ),
    Regel(
        r"\b(garantiert|guaranteed|risikofrei|risk[- ]free|sicherer gewinn|"
        r"can'?t lose|kann nicht verlieren)\b",
        60,
        "Garantierte oder risikofreie Rendite versprochen. Das existiert in "
        "dieser Anlageklasse nicht - wer es behauptet, weiss das",
    ),
    Regel(
        r"\b(\d{2,4})\s?x\b(?!\s?(leverage|hebel))",
        25,
        "Konkretes Kursziel als Vielfaches genannt. Niemand kann das wissen; "
        "die Zahl dient dazu, Dringlichkeit zu erzeugen",
    ),
    Regel(
        r"\b(nur noch|only|letzte chance|last chance|limited|begrenzt|"
        r"spots left|plaetze frei|plätze frei|countdown|endet in|ends in)\b",
        30,
        "Kuenstliche Verknappung und Zeitdruck. Soll verhindern, dass du "
        "nachdenkst oder nachprüfst",
    ),
    Regel(
        r"\b(referral|ref[- ]?code|einladungslink|invite link|affiliate)\b",
        45,
        "Empfehlungssystem. Wer Werber belohnt, finanziert Auszahlungen aus "
        "neuen Einzahlungen - das ist die Struktur eines Schneeballsystems",
    ),
    Regel(
        r"\b(insider|inside info|geheimtipp|vorab[- ]?info|early access|"
        r"guaranteed allocation|garantierte allokation)\b",
        50,
        "Behauptet einen Informationsvorsprung. In einer Gruppe, die diesen "
        "Vorsprung teilt, ist er keiner mehr - du bist dort nicht der "
        "Insider, sondern dessen Gegenseite",
    ),
    Regel(
        r"\b(cex|binance|coinbase|bybit|okx|kraken)\b[^.\n]{0,30}"
        r"\b(listing|gelistet|confirmed|bestaetigt|bestätigt)\b",
        55,
        "Boersenlisting behauptet. Boersen kuendigen Listings selbst an und "
        "nie vorab ueber Werbekanaele",
    ),
    Regel(
        r"\b(dm me|schreib mir|pm me|privat schreiben|direktnachricht)\b",
        35,
        "Fordert zur Privatnachricht auf. Dort gibt es keine Zeugen und keine "
        "Historie - der uebliche Ort fuer den zweiten Schritt",
    ),
    Regel(
        r"\b(audit(ed)?|gepr(ue|ü)ft|kyc)\b",
        15,
        "Pruefung oder KYC behauptet. Ohne verlinkten, aufrufbaren Bericht "
        "einer benannten Firma ist das eine Behauptung wie jede andere",
    ),
    Regel(
        r"\b(doxxed|doxed|team bekannt|bekanntes team)\b",
        15,
        "Offengelegtes Team behauptet. Ohne nachpruefbare Namen ist auch das "
        "nur eine Behauptung",
    ),
    Regel(
        r"\b(next (doge|shib|pepe|bonk|wif)|der naechste|der nächste)\b",
        20,
        "Vergleich mit einem vergangenen Gewinner. Fuer jeden davon gibt es "
        "zehntausende, die auf null gingen - die werden nie zitiert",
    ),
)


@dataclass
class Textbefund:
    punkte: int = 0
    treffer: list[tuple[int, str]] = field(default_factory=list)
    toedlich: bool = False

    @property
    def einstufung(self) -> str:
        if self.toedlich:
            return "BETRUGSMUSTER"
        if self.punkte >= 90:
            return "HOCHVERDAECHTIG"
        if self.punkte >= 45:
            return "AUFFAELLIG"
        if self.punkte > 0:
            return "UEBLICHE WERBUNG"
        return "UNAUFFAELLIG"


def pruefe_text(text: str | None) -> Textbefund:
    """Sucht bekannte Betrugsmuster im Ankuendigungstext."""
    befund = Textbefund()
    if not text or not text.strip():
        return befund

    for regel in REGELN:
        if re.search(regel.muster, text, re.IGNORECASE):
            befund.punkte += regel.gewicht
            befund.treffer.append((regel.gewicht, regel.erklaerung))
            if regel.gewicht >= 100:
                befund.toedlich = True

    befund.treffer.sort(key=lambda t: t[0], reverse=True)
    befund.punkte = min(befund.punkte, 200)
    return befund


# --------------------------------------------------------------------- #
def pruefe_namenskollision(paare: list[dict], ticker: str) -> tuple[int, int]:
    """Wie viele Token tragen dieses Kuerzel schon - und wie viele sind tot?

    Betrugsfabriken verwenden Namen wieder. Ein Kuerzel, das bereits
    dutzendfach existiert und fast ueberall tot ist, ist ein Muster.
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return 0, 0

    gesehen: dict[str, float] = {}
    for paar in paare:
        basis = paar.get("baseToken") or {}
        if str(basis.get("symbol", "")).strip().upper() != ticker:
            continue
        adresse = str(basis.get("address") or "")
        if not adresse:
            continue
        liq = paar.get("liquidity") or {}
        try:
            wert = float(liq.get("usd") or 0.0)
        except (TypeError, ValueError):
            wert = 0.0
        gesehen[adresse] = max(gesehen.get(adresse, 0.0), wert)

    tot = sum(1 for wert in gesehen.values() if wert < 1_000)
    return len(gesehen), tot


# --------------------------------------------------------------------- #
class CallRegister:
    """Speichert Ankuendigungen und was daraus wurde."""

    def __init__(self, pfad: str = "radar-calls.sqlite3") -> None:
        self.conn = sqlite3.connect(pfad)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "CallRegister":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def add(self, name: str, promoter: str, ticker: str | None = None,
            kanal: str | None = None, start_geplant: str | None = None,
            promo_text: str | None = None, presale_adresse: str | None = None,
            notiz: str | None = None) -> int:
        if not name.strip() or not promoter.strip():
            raise ValueError("Name und Promoter muessen angegeben werden")
        cur = self.conn.execute(
            "INSERT INTO calls (name, ticker, promoter, kanal, erfasst_am,"
            " start_geplant, promo_text, presale_adresse, notiz)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (name.strip(), (ticker or "").strip().upper() or None, promoter.strip(),
             kanal, int(time.time()), start_geplant, promo_text,
             presale_adresse, notiz),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def get(self, call_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        return dict(row) if row else None

    def liste(self, nur_offen: bool = False, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM calls"
        if nur_offen:
            sql += " WHERE status = 'offen'"
        sql += " ORDER BY erfasst_am DESC LIMIT ?"
        return [dict(r) for r in self.conn.execute(sql, (limit,)).fetchall()]

    def verknuepfe(self, call_id: int, mint: str, score: int, phase: str,
                   liquiditaet: float, ausschluss: bool) -> None:
        """Haelt fest, was beim tatsaechlichen Start herauskam."""
        self.conn.execute(
            "UPDATE calls SET status = 'gelauncht', mint = ?, verknuepft_am = ?,"
            " score_beim_start = ?, phase_beim_start = ?, liquiditaet_beim_start = ?,"
            " ausschluss_beim_start = ? WHERE id = ?",
            (mint, int(time.time()), score, phase, liquiditaet,
             1 if ausschluss else 0, call_id),
        )
        self.conn.commit()

    def setze_status(self, call_id: int, status: str) -> None:
        if status not in ("offen", "gelauncht", "verschwunden"):
            raise ValueError(f"Unbekannter Status: {status}")
        self.conn.execute("UPDATE calls SET status = ? WHERE id = ?", (status, call_id))
        self.conn.commit()

    # ----------------------------------------------------------------- #
    def promoter_bilanz(self) -> list[dict]:
        """Die eigentliche Kennzahl: was ist aus den Calls jedes Promoters geworden."""
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM calls").fetchall()]
        nach_promoter: dict[str, list[dict]] = {}
        for row in rows:
            nach_promoter.setdefault(row["promoter"], []).append(row)

        bilanz = []
        for promoter, calls in nach_promoter.items():
            gelauncht = [c for c in calls if c["status"] == "gelauncht"]
            verschwunden = [c for c in calls if c["status"] == "verschwunden"]
            ausschluss = [c for c in gelauncht if c["ausschluss_beim_start"]]
            scores = [c["score_beim_start"] for c in gelauncht
                      if c["score_beim_start"] is not None]

            bilanz.append({
                "promoter": promoter,
                "calls": len(calls),
                "gelauncht": len(gelauncht),
                "verschwunden": len(verschwunden),
                "offen": len(calls) - len(gelauncht) - len(verschwunden),
                "ausschluss": len(ausschluss),
                "schnitt_score": (sum(scores) / len(scores)) if scores else None,
            })

        # Schlechteste zuerst - das ist die Information, die zaehlt.
        bilanz.sort(key=lambda b: (
            -(b["ausschluss"] + b["verschwunden"]) / b["calls"] if b["calls"] else 0,
            -b["calls"],
        ))
        return bilanz


def bewerte_promoter(eintrag: dict) -> str:
    """Klartext-Urteil zu einer Promoter-Bilanz."""
    calls = eintrag["calls"]
    entschieden = eintrag["gelauncht"] + eintrag["verschwunden"]
    schlecht = eintrag["ausschluss"] + eintrag["verschwunden"]

    if entschieden < 5:
        return f"Noch zu wenig Datenlage ({entschieden} entschieden von {calls})"

    quote = schlecht / entschieden
    if quote >= 0.8:
        return f"{quote * 100:.0f}% der Calls waren wertlos - dieser Quelle zu folgen kostet Geld"
    if quote >= 0.5:
        return f"{quote * 100:.0f}% wertlos - schlechter als eine Muenze"
    if quote >= 0.25:
        return f"{quote * 100:.0f}% wertlos - unterdurchschnittlich, aber nicht nur Schrott"
    return f"Nur {quote * 100:.0f}% wertlos - auffaellig gut, weiter beobachten"
