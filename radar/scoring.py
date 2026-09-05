"""Bewertung eines Tokens: harte Ausschlusskriterien, Punkte, FOMO-Phase.

Die Grundannahme: die meisten Memecoins gehen auf null. Aufgabe dieses Moduls
ist nicht, Gewinner zu finden, sondern Verlierer *vorher* auszusortieren -
und zu erkennen, in welcher Phase des Pumps du gerade einsteigen wuerdest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .config import Thresholds
from .model import TokenSnapshot


class Stage(Enum):
    """Phase im typischen Memecoin-Lebenszyklus."""

    UNBEKANNT = "unbekannt"
    FRUEH = "frueh"
    MOMENTUM = "momentum"
    BLOWOFF = "blowoff"
    NACH_DUMP = "nach_dump"
    TOT = "tot"

    @property
    def erklaerung(self) -> str:
        return {
            Stage.UNBEKANNT: "Zu wenig Daten fuer eine Phaseneinordnung.",
            Stage.FRUEH: "Jung, Fluss baut sich auf. Hoechste Chance, hoechstes Rugrisiko.",
            Stage.MOMENTUM: "Laeuft geordnet. Kaeufer und Verkaeufer halbwegs im Gleichgewicht.",
            Stage.BLOWOFF: (
                "Senkrechte Kerze bei einseitigem Kaufdruck. Wer JETZT kauft, "
                "liefert denen den Ausstieg, die vorher drin waren. Das ist der "
                "Moment, in dem Signalgruppen posten."
            ),
            Stage.NACH_DUMP: "Der Ausstieg ist gelaufen. 'Guenstig' heisst hier nur: billiger als der Betrug.",
            Stage.TOT: "Kein Fluss mehr. Restwert tendiert gegen null.",
        }[self]


TIER_ORDER = ["NO-GO", "GEFAEHRLICH", "SPEKULATIV", "BEOBACHTEN"]


@dataclass
class Verdict:
    snapshot: TokenSnapshot
    score: int = 0
    tier: str = "NO-GO"
    stage: Stage = Stage.UNBEKANNT
    hard_fails: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    positives: list[str] = field(default_factory=list)
    contract_notes: list[str] = field(default_factory=list)
    contract_checked: bool = False

    @property
    def tradeable(self) -> bool:
        return not self.hard_fails and self.tier in ("SPEKULATIV", "BEOBACHTEN")


def detect_stage(snap: TokenSnapshot, th: Thresholds) -> Stage:
    """Ordnet den Token in den Pump-Zyklus ein."""
    change_m5 = snap.price_change.get("m5", 0.0)
    change_h1 = snap.price_change.get("h1", 0.0)
    change_h6 = snap.price_change.get("h6", 0.0)
    age = snap.age_minutes

    if snap.txns_h1 < 10 and snap.volume.get("h1", 0.0) < snap.liquidity_usd * 0.02:
        return Stage.TOT

    # Blowoff zuerst pruefen: das ist die teuerste Fehleinschaetzung.
    blowoff_candle = change_m5 >= th.blowoff_change_m5
    parabolic = change_h1 >= th.blowoff_change_h1
    one_sided = snap.buy_ratio_h1 >= 0.75
    if (blowoff_candle and one_sided) or (parabolic and one_sided):
        return Stage.BLOWOFF

    if change_h1 <= th.postdump_change_h1 and change_h6 > 0:
        return Stage.NACH_DUMP

    if 0 <= age <= th.good_age_minutes and snap.txns_h1 >= th.min_txns_h1:
        return Stage.FRUEH

    if change_h1 > 0 and 0.40 <= snap.buy_ratio_h1 <= 0.75 and snap.txns_h1 >= th.min_txns_h1:
        return Stage.MOMENTUM

    if age < 0:
        return Stage.UNBEKANNT
    return Stage.MOMENTUM if change_h1 > -15 else Stage.NACH_DUMP


def _check_hard_filters(snap: TokenSnapshot, th: Thresholds) -> list[str]:
    """K.-o.-Kriterien. Jeder Treffer heisst: Finger weg, egal wie gut der Rest aussieht."""
    fails: list[str] = []

    if snap.liquidity_usd < th.min_liquidity_usd:
        fails.append(
            f"Liquiditaet {snap.liquidity_usd:,.0f} USD < {th.min_liquidity_usd:,.0f} USD "
            "- du kommst nicht ohne massiven Verlust wieder raus"
        )

    if snap.mcap_to_liquidity > th.max_mcap_to_liquidity:
        ratio = snap.mcap_to_liquidity
        shown = "unendlich" if ratio == float("inf") else f"{ratio:.0f}x"
        fails.append(
            f"Bewertung/Liquiditaet {shown} > {th.max_mcap_to_liquidity:.0f}x "
            "- die Marktkapitalisierung existiert nur auf dem Papier"
        )

    age = snap.age_minutes
    if 0 <= age < th.min_age_minutes:
        fails.append(f"Erst {age:.0f} Min. alt - keine belastbaren Daten, reines Sniper-Revier")
    elif age > th.max_age_minutes:
        fails.append(f"{age / 60:.0f} Std. alt ohne neue Dynamik - der Zug ist durch")

    if snap.txns_h1 < th.min_txns_h1:
        fails.append(f"Nur {snap.txns_h1} Trades/Std. - kein echter Markt, nur Bots")

    turnover = snap.turnover_h1
    if turnover > th.max_turnover_h1:
        fails.append(
            f"Umschlag {turnover:.1f}x der Liquiditaet pro Stunde - "
            "das ist Wash-Trading fuers Ranking, kein echter Fluss"
        )

    if snap.buy_ratio_h1 > th.max_buy_ratio_h1:
        fails.append(
            f"{snap.buy_ratio_h1 * 100:.0f}% Kaeufe - eine koordinierte Kampagne "
            "baut gerade ihre Gegenseite auf. Du waerst die Gegenseite"
        )
    elif snap.buy_ratio_h1 < th.min_buy_ratio_h1:
        fails.append(f"Nur {snap.buy_ratio_h1 * 100:.0f}% Kaeufe - der Ausstieg laeuft bereits")

    if snap.price_usd <= 0:
        fails.append("Kein gueltiger Preis - Paar vermutlich tot oder fehlerhaft")

    return fails


def _score_soft(snap: TokenSnapshot, th: Thresholds) -> tuple[int, list[str], list[str]]:
    """Weiche Bewertung 0-100 mit Begruendungen."""
    score = 50
    positives: list[str] = []
    warnings: list[str] = []

    if snap.liquidity_usd >= th.good_liquidity_usd:
        score += 15
        positives.append(f"Solide Liquiditaet ({snap.liquidity_usd:,.0f} USD)")
    elif snap.liquidity_usd >= th.min_liquidity_usd * 2:
        score += 7
        positives.append(f"Ausreichende Liquiditaet ({snap.liquidity_usd:,.0f} USD)")
    else:
        warnings.append("Liquiditaet nur knapp ueber der Schmerzgrenze")

    if snap.txns_h1 >= th.good_txns_h1:
        score += 12
        positives.append(f"Reger Handel ({snap.txns_h1} Trades/Std.)")
    elif snap.txns_h1 >= th.min_txns_h1 * 2:
        score += 5

    ratio = snap.buy_ratio_h1
    if 0.45 <= ratio <= 0.65:
        score += 10
        positives.append(f"Ausgeglichener Fluss ({ratio * 100:.0f}% Kaeufe) - echter Markt")
    elif ratio > 0.75:
        score -= 12
        warnings.append(f"Kaufdruck {ratio * 100:.0f}% ist einseitig - typisch kurz vor dem Ausstieg")

    turnover = snap.turnover_h1
    if 0.5 <= turnover <= 5.0:
        score += 8
        positives.append(f"Gesunder Umschlag ({turnover:.1f}x)")
    elif turnover < th.min_turnover_h1:
        score -= 10
        warnings.append("Kaum Umschlag - das Interesse ist weg")

    mcap_ratio = snap.mcap_to_liquidity
    if mcap_ratio <= 8:
        score += 10
        positives.append(f"Bewertung durch Liquiditaet gedeckt ({mcap_ratio:.1f}x)")
    elif mcap_ratio > 15:
        score -= 8
        warnings.append(f"Bewertung {mcap_ratio:.0f}x der Liquiditaet - duenn unterlegt")

    if snap.has_links:
        score += 5
        positives.append(f"{snap.socials} Social-Links, {snap.websites} Website(s) hinterlegt")
    else:
        score -= 8
        warnings.append("Keine Website, keine Socials - niemand steht dazu")

    if snap.boosts > 0:
        warnings.append(
            f"{snap.boosts} bezahlte Boosts aktiv - gekaufte Aufmerksamkeit, "
            "kein Qualitaetssignal. Jemand bezahlt dafuer, dass du das hier siehst"
        )
        score -= 4

    trend_h6 = snap.price_change.get("h6", 0.0)
    if trend_h6 > 500:
        score -= 15
        warnings.append(f"Bereits +{trend_h6:.0f}% in 6 Std. - die Bewegung ist gelaufen")

    return max(0, min(100, score)), positives, warnings


def _apply_contract_report(verdict: Verdict, report: dict | None) -> None:
    """Wertet einen RugCheck-Report aus, falls vorhanden."""
    if not isinstance(report, dict):
        verdict.contract_notes.append(
            "Vertragspruefung nicht verfuegbar - Mint-/Freeze-Authority und "
            "LP-Lock ungeprueft. Ohne diese Pruefung ist jede Bewertung unvollstaendig"
        )
        return

    verdict.contract_checked = True
    token = report.get("token") or {}
    if report.get("_quelle") == "rpc":
        verdict.contract_notes.append(
            "Quelle: eigener RPC-Knoten (Authorities direkt aus dem Mint-Konto). "
            "Die Sperrung der Liquiditaet laesst sich so allein nicht pruefen"
        )

    if token.get("mintAuthority"):
        verdict.hard_fails.append(
            "Mint-Authority aktiv - der Ersteller kann jederzeit beliebig "
            "Token nachdrucken und dich auf null verwaessern"
        )
    else:
        verdict.contract_notes.append("Mint-Authority abgegeben")

    if token.get("freezeAuthority"):
        verdict.hard_fails.append(
            "Freeze-Authority aktiv - dein Wallet kann eingefroren werden. "
            "Du kaufst dann etwas, das du nicht mehr verkaufen kannst"
        )
    else:
        verdict.contract_notes.append("Freeze-Authority abgegeben")

    lp_locked = _extract_lp_locked(report)
    if lp_locked is not None:
        if lp_locked < 50:
            verdict.hard_fails.append(
                f"Nur {lp_locked:.0f}% der Liquiditaet gesperrt - der Rest kann "
                "in einer einzigen Transaktion abgezogen werden"
            )
        else:
            verdict.contract_notes.append(f"{lp_locked:.0f}% der Liquiditaet gesperrt")

    top_pct = _extract_top_holder_pct(report)
    if top_pct is not None:
        if top_pct > 25:
            verdict.hard_fails.append(
                f"Groesster Halter (ohne Pool) haelt {top_pct:.0f}% - eine einzige "
                "Verkaufsorder beendet den Token"
            )
        elif top_pct > 12:
            verdict.warnings.append(f"Groesster Halter haelt {top_pct:.0f}% - Klumpenrisiko")
        else:
            verdict.contract_notes.append(f"Groesster Halter {top_pct:.0f}% - gut verteilt")

    # Halterliste direkt vom Knoten: enthaelt zwangslaeufig die Pool-Konten,
    # weil ein reiner RPC-Abruf Pool und Wallet nicht unterscheiden kann.
    # Deshalb nur Warnung - ein Ausschluss waere hier oft schlicht falsch.
    if top_pct is None and report.get("topHoldersRpc"):
        eintraege = [e for e in report["topHoldersRpc"] if isinstance(e, dict)]
        if eintraege:
            groesster = max(_to_pct(e.get("pct")) for e in eintraege)
            ohne_groessten = sorted(
                (_to_pct(e.get("pct")) for e in eintraege), reverse=True
            )[1:2]
            zweiter = ohne_groessten[0] if ohne_groessten else 0.0
            verdict.contract_notes.append(
                f"Groesstes Token-Konto {groesster:.0f}% (enthaelt den "
                f"Liquiditaetspool), zweitgroesstes {zweiter:.0f}%"
            )
            if zweiter > 15:
                verdict.warnings.append(
                    f"Zweitgroesster Halter haelt {zweiter:.0f}% - Klumpenrisiko. "
                    "Ob das eine Wallet oder ein weiterer Pool ist, kann ein "
                    "reiner Knotenabruf nicht aufloesen"
                )

    for risk in report.get("risks") or []:
        if not isinstance(risk, dict):
            continue
        name = str(risk.get("name") or "Risiko")
        description = str(risk.get("description") or "")
        level = str(risk.get("level") or "").lower()
        text = f"{name}: {description}".strip(": ")
        if level in ("danger", "critical", "high"):
            verdict.hard_fails.append(f"RugCheck: {text}")
        elif level in ("warn", "warning", "medium"):
            verdict.warnings.append(f"RugCheck: {text}")


def _to_pct(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _extract_lp_locked(report: dict) -> float | None:
    markets = report.get("markets")
    if isinstance(markets, list):
        for market in markets:
            if not isinstance(market, dict):
                continue
            lp = market.get("lp")
            if isinstance(lp, dict):
                for key in ("lpLockedPct", "lpLockedPercentage"):
                    if lp.get(key) is not None:
                        try:
                            return float(lp[key])
                        except (TypeError, ValueError):
                            continue
    for key in ("lpLockedPct", "totalLPProvidersPct"):
        if report.get(key) is not None:
            try:
                return float(report[key])
            except (TypeError, ValueError):
                pass
    return None


def _extract_top_holder_pct(report: dict) -> float | None:
    holders = report.get("topHolders")
    if not isinstance(holders, list):
        return None
    best: float | None = None
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        # Pool-/Vault-Adressen sind kein Klumpenrisiko, sondern die Liquiditaet selbst.
        if holder.get("insider") is False and holder.get("owner") in (None, ""):
            continue
        try:
            pct = float(holder.get("pct"))
        except (TypeError, ValueError):
            continue
        if best is None or pct > best:
            best = pct
    return best


def evaluate(
    snap: TokenSnapshot,
    thresholds: Thresholds | None = None,
    contract_report: dict | None = None,
) -> Verdict:
    """Vollstaendige Bewertung eines Tokens."""
    th = thresholds or Thresholds()
    verdict = Verdict(snapshot=snap)

    verdict.hard_fails = _check_hard_filters(snap, th)
    verdict.score, verdict.positives, verdict.warnings = _score_soft(snap, th)
    verdict.stage = detect_stage(snap, th)

    _apply_contract_report(verdict, contract_report)

    if verdict.stage is Stage.BLOWOFF:
        verdict.score = min(verdict.score, 25)
        verdict.warnings.insert(0, "FOMO-Phase erkannt: " + Stage.BLOWOFF.erklaerung)
    elif verdict.stage is Stage.NACH_DUMP:
        verdict.score = min(verdict.score, 20)
    elif verdict.stage is Stage.TOT:
        verdict.score = min(verdict.score, 10)

    # Obergrenzen. In dieser Anlageklasse gibt es keine "sichere" Bewertung -
    # eine 100 waere eine Luege, die zu grossen Positionen verleitet.
    verdict.score = min(verdict.score, 90)
    if not verdict.contract_checked:
        # Ohne Mint-/Freeze-/LP-Pruefung fehlen genau die Angaben, an denen
        # ein Rug erkennbar waere. Bestenfalls "spekulativ".
        verdict.score = min(verdict.score, 65)

    if verdict.hard_fails:
        verdict.tier = "NO-GO"
        verdict.score = min(verdict.score, 15)
    elif verdict.score >= 70:
        verdict.tier = "BEOBACHTEN"
    elif verdict.score >= 50:
        verdict.tier = "SPEKULATIV"
    else:
        verdict.tier = "GEFAEHRLICH"

    return verdict
