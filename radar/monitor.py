"""Dauerbetrieb: neue Token erfassen, reifen lassen, bei Eignung melden.

Die zentrale Einsicht hinter dem Aufbau: ein gerade gestarteter Token faellt
durch die eigenen Filter. Unter zehn Minuten Alter gibt es keine belastbaren
Daten - Liquiditaet, Kaufverhaeltnis und Umschlag sind noch Rauschen. Ein
Alarm im Moment des Starts waere deshalb wertlos.

Der Monitor meldet stattdessen erst, wenn ein Token reif genug geworden ist,
um ueberhaupt bewertbar zu sein, UND die Filter besteht. Bis dahin steht er
auf einer Beobachtungsliste und wird nach Alter gestaffelt nachverfolgt.
"""

from __future__ import annotations

import signal
import sqlite3
import time
from dataclasses import dataclass

from .config import Settings, Thresholds
from .model import TokenSnapshot
from .notify import Alert, Notifier
from .scoring import Stage, Verdict, evaluate
from .sources import DexScreener, SourceError

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    mint            TEXT PRIMARY KEY,
    symbol          TEXT,
    first_seen      INTEGER NOT NULL,
    last_checked    INTEGER,
    next_check      INTEGER NOT NULL,
    checks          INTEGER NOT NULL DEFAULT 0,
    best_score      INTEGER NOT NULL DEFAULT 0,
    last_score      INTEGER NOT NULL DEFAULT 0,
    last_stage      TEXT,
    discovered_via  TEXT,
    alerted_kandidat INTEGER NOT NULL DEFAULT 0,
    alerted_ausstieg INTEGER NOT NULL DEFAULT 0,
    dropped         INTEGER NOT NULL DEFAULT 0,
    drop_reason     TEXT
);
CREATE INDEX IF NOT EXISTS idx_watch_due ON watchlist(dropped, next_check);
"""


# --------------------------------------------------------------------- #
# Reine Planungslogik - ohne Netzwerk und ohne Datenbank testbar.
# --------------------------------------------------------------------- #
def next_interval_seconds(age_minutes: float, score: int, th: Thresholds) -> int:
    """Wie lange bis zur naechsten Pruefung.

    Junge Token aendern sich im Minutentakt und brauchen enge Kontrolle;
    alte kaum noch. Das Anfragebudget ist knapp, also bekommt es der,
    bei dem sich noch etwas entscheidet.
    """
    if age_minutes < 0:
        return 300

    # Kurz vor der Mindestreife: engmaschig, hier faellt die Entscheidung.
    if age_minutes < th.min_age_minutes:
        return 90
    if age_minutes < 45:
        return 150
    if age_minutes < 180:
        return 300
    if age_minutes < 720:
        return 900

    # Alte Token nur noch selten - ausser sie waren zuletzt aussichtsreich.
    return 1200 if score >= 50 else 2400


def should_drop(snap: TokenSnapshot | None, verdict: Verdict | None,
                th: Thresholds, checks: int) -> str | None:
    """Grund, den Token von der Liste zu nehmen - oder None zum Behalten."""
    if snap is None:
        # Kein Handelspaar auffindbar. Nach mehreren Versuchen aufgeben.
        return "kein Handelspaar auffindbar" if checks >= 3 else None

    if snap.age_minutes > th.max_age_minutes:
        return "zu alt, keine neue Dynamik"

    if verdict is not None and verdict.stage is Stage.TOT:
        return "kein Fluss mehr - tot"

    if snap.liquidity_usd < th.min_liquidity_usd * 0.4:
        # Deutlich unter der Schmerzgrenze: entweder nie gestartet oder
        # die Liquiditaet wurde abgezogen. Beides ist endgueltig.
        return f"Liquiditaet auf {snap.liquidity_usd:,.0f} USD gefallen"

    return None


def alert_kind(verdict: Verdict, already_alerted: bool, min_score: int) -> str | None:
    """Welcher Alarm - falls ueberhaupt einer faellig ist."""
    # Ausstiegssignal hat Vorrang: nur relevant fuer bereits gemeldete Token.
    if already_alerted and verdict.stage is Stage.BLOWOFF:
        return "ausstieg"

    if already_alerted:
        return None

    if verdict.hard_fails:
        return None
    if verdict.stage in (Stage.BLOWOFF, Stage.NACH_DUMP, Stage.TOT):
        return None
    if verdict.score < min_score:
        return None
    return "kandidat"


# --------------------------------------------------------------------- #
class RateBudget:
    """Einfaches Anfragebudget pro Minute.

    DexScreener limitiert bei etwa 60 Anfragen/Minute. Wer darueber geht,
    bekommt HTTP 429 und faellt fuer eine Weile ganz aus - deshalb bleibt
    die Voreinstellung bewusst darunter.
    """

    def __init__(self, per_minute: int = 50) -> None:
        self.per_minute = per_minute
        self._window_start = time.monotonic()
        self._used = 0

    def take(self, count: int = 1) -> bool:
        now = time.monotonic()
        if now - self._window_start >= 60.0:
            self._window_start = now
            self._used = 0
        if self._used + count > self.per_minute:
            return False
        self._used += count
        return True

    @property
    def remaining(self) -> int:
        if time.monotonic() - self._window_start >= 60.0:
            return self.per_minute
        return max(0, self.per_minute - self._used)


class Watchlist:
    """Beobachtungsliste, ueberlebt Neustarts."""

    def __init__(self, path: str = "radar-watchlist.sqlite3") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Watchlist":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def add(self, mint: str, via: str) -> bool:
        """True, wenn der Token neu war."""
        now = int(time.time())
        try:
            self.conn.execute(
                "INSERT INTO watchlist (mint, first_seen, next_check, discovered_via)"
                " VALUES (?,?,?,?)",
                (mint, now, now, via),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # kennen wir schon

    def due(self, limit: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM watchlist WHERE dropped = 0 AND next_check <= ?"
            " ORDER BY next_check ASC LIMIT ?",
            (int(time.time()), limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_after_check(self, mint: str, symbol: str, score: int, stage: str,
                           interval: int, best: int) -> None:
        now = int(time.time())
        self.conn.execute(
            "UPDATE watchlist SET symbol = ?, last_checked = ?, next_check = ?,"
            " checks = checks + 1, last_score = ?, best_score = ?, last_stage = ?"
            " WHERE mint = ?",
            (symbol, now, now + interval, score, best, stage, mint),
        )
        self.conn.commit()

    def bump_failed_check(self, mint: str, interval: int = 300) -> None:
        now = int(time.time())
        self.conn.execute(
            "UPDATE watchlist SET last_checked = ?, next_check = ?, checks = checks + 1"
            " WHERE mint = ?",
            (now, now + interval, mint),
        )
        self.conn.commit()

    def mark_alerted(self, mint: str, kind: str) -> None:
        column = "alerted_kandidat" if kind == "kandidat" else "alerted_ausstieg"
        self.conn.execute(f"UPDATE watchlist SET {column} = 1 WHERE mint = ?", (mint,))
        self.conn.commit()

    def drop(self, mint: str, reason: str) -> None:
        self.conn.execute(
            "UPDATE watchlist SET dropped = 1, drop_reason = ? WHERE mint = ?",
            (reason, mint),
        )
        self.conn.commit()

    def stats(self) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) AS gesamt,"
            " SUM(CASE WHEN dropped = 0 THEN 1 ELSE 0 END) AS aktiv,"
            " SUM(alerted_kandidat) AS gemeldet"
            " FROM watchlist"
        ).fetchone()
        return {
            "gesamt": row["gesamt"] or 0,
            "aktiv": row["aktiv"] or 0,
            "gemeldet": row["gemeldet"] or 0,
        }


# --------------------------------------------------------------------- #
@dataclass
class MonitorConfig:
    min_score: int = 55
    discovery_interval: int = 300
    """Sekunden zwischen zwei Suchlaeufen nach neuen Token."""
    requests_per_minute: int = 50
    max_watchlist: int = 400
    tick_seconds: int = 15
    quiet: bool = False


class Monitor:
    def __init__(self, settings: Settings, dex: DexScreener, watchlist: Watchlist,
                 notifier: Notifier, config: MonitorConfig | None = None) -> None:
        self.settings = settings
        self.dex = dex
        self.watchlist = watchlist
        self.notifier = notifier
        self.config = config or MonitorConfig()
        self.budget = RateBudget(self.config.requests_per_minute)
        self._stop = False
        # None = noch nie gesucht. Kein 0.0-Sentinel: time.monotonic()
        # hat keinen definierten Nullpunkt - in einem frisch gestarteten
        # Container zaehlt es ab Null, und der erste Suchlauf bliebe dann
        # bis zum Ablauf des Intervalls aus.
        self._last_discovery: float | None = None
        self.counters = {"entdeckt": 0, "geprueft": 0, "gemeldet": 0, "verworfen": 0}

    def request_stop(self, *_: object) -> None:
        self._stop = True

    # ----------------------------------------------------------------- #
    def discovery_due(self) -> bool:
        """Beim allerersten Durchlauf immer, danach nach Intervall."""
        if self._last_discovery is None:
            return True
        return time.monotonic() - self._last_discovery >= self.config.discovery_interval

    def discover(self) -> int:
        """Neue Token aus den Listing-Endpunkten aufnehmen."""
        if not self.budget.take(2):
            return 0

        neu = 0
        quellen: list[tuple[list, str]] = []
        try:
            quellen.append((self.dex.token_profiles(), "profil"))
        except SourceError as exc:
            self._log(f"Suchlauf (Profile) fehlgeschlagen: {exc}")
        try:
            quellen.append((self.dex.boosted(top=False), "boost"))
        except SourceError as exc:
            self._log(f"Suchlauf (Boosts) fehlgeschlagen: {exc}")

        for eintraege, via in quellen:
            for eintrag in eintraege or []:
                if not isinstance(eintrag, dict):
                    continue
                if eintrag.get("chainId") != self.settings.chain:
                    continue
                mint = eintrag.get("tokenAddress")
                if mint and self.watchlist.add(str(mint), via):
                    neu += 1

        self.counters["entdeckt"] += neu
        self._last_discovery = time.monotonic()
        return neu

    def check_one(self, row: dict) -> None:
        """Einen Token der Liste pruefen, bewerten und ggf. melden."""
        mint = row["mint"]
        th = self.settings.thresholds

        try:
            pairs = self.dex.pairs_for_token(mint, self.settings.chain)
        except SourceError:
            self.watchlist.bump_failed_check(mint)
            return

        snap = TokenSnapshot.from_pair(pairs[0]) if pairs else None
        verdict = evaluate(snap, th, None) if snap else None
        self.counters["geprueft"] += 1

        grund = should_drop(snap, verdict, th, row["checks"] + 1)
        if grund:
            self.watchlist.drop(mint, grund)
            self.counters["verworfen"] += 1
            return

        if snap is None or verdict is None:
            self.watchlist.bump_failed_check(mint)
            return

        best = max(row["best_score"], verdict.score)
        self.watchlist.update_after_check(
            mint, snap.symbol, verdict.score, verdict.stage.value,
            next_interval_seconds(snap.age_minutes, verdict.score, th), best,
        )

        art = alert_kind(verdict, bool(row["alerted_kandidat"]), self.config.min_score)
        if art:
            self._alarm(art, snap, verdict)

    def _alarm(self, art: str, snap: TokenSnapshot, verdict: Verdict) -> None:
        if art == "ausstieg":
            zeilen = ["", "Der zuvor gemeldete Token ist in die Blowoff-Phase gelaufen.",
                      "Falls du drin bist: das ist der Bereich, in dem verkauft wird,",
                      "nicht der, in dem nachgekauft wird."]
        else:
            zeilen = [""] + [f"+ {p}" for p in verdict.positives[:4]]
            if verdict.warnings:
                zeilen += [f"! {w}" for w in verdict.warnings[:3]]
            if not verdict.contract_checked:
                zeilen.append("? Vertragspruefung fehlt - Mint-/Freeze-Authority ungeprueft")

        alert = Alert(
            kind=art, symbol=snap.symbol, mint=snap.mint, score=verdict.score,
            stage=verdict.stage.value, price_usd=snap.price_usd,
            liquidity_usd=snap.liquidity_usd, age_minutes=snap.age_minutes,
            url=snap.url, lines=zeilen,
        )
        try:
            self.notifier.send(alert)
        except Exception as exc:  # Ein Kanalfehler darf den Monitor nie stoppen
            self._log(f"Alarm konnte nicht zugestellt werden: {exc}")
        self.watchlist.mark_alerted(snap.mint, art)
        self.counters["gemeldet"] += 1

    # ----------------------------------------------------------------- #
    def tick(self) -> None:
        """Ein Durchlauf: ggf. suchen, dann faellige Token im Budget pruefen."""
        if self.discovery_due():
            stats = self.watchlist.stats()
            if stats["aktiv"] < self.config.max_watchlist:
                neu = self.discover()
                if neu:
                    self._log(f"{neu} neue Token aufgenommen "
                              f"(Liste: {stats['aktiv'] + neu} aktiv)")

        faellig = self.watchlist.due(limit=max(0, self.budget.remaining))
        for row in faellig:
            if self._stop or not self.budget.take(1):
                break
            self.check_one(row)

    def run(self, max_ticks: int | None = None) -> int:
        """Hauptschleife. max_ticks begrenzt die Laeufe (fuer Tests und --once)."""
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        ticks = 0
        while not self._stop:
            self.tick()
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            if not self._stop:
                time.sleep(self.config.tick_seconds)

        stats = self.watchlist.stats()
        self._log("")
        self._log(f"Beendet nach {ticks} Durchlaeufen. "
                  f"Entdeckt {self.counters['entdeckt']}, "
                  f"geprueft {self.counters['geprueft']}, "
                  f"gemeldet {self.counters['gemeldet']}, "
                  f"verworfen {self.counters['verworfen']}. "
                  f"Liste: {stats['aktiv']} aktiv von {stats['gesamt']}.")
        return 0

    def _log(self, message: str) -> None:
        if not self.config.quiet:
            print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)
