"""Textausgabe der Analyse - bewusst nuechtern, ohne Hype-Formatierung."""

from __future__ import annotations

import textwrap

from .risk import PositionPlan
from .scoring import Stage, Verdict

TIER_MARK = {
    "NO-GO": "[NO-GO]",
    "GEFAEHRLICH": "[GEFAEHRLICH]",
    "SPEKULATIV": "[SPEKULATIV]",
    "BEOBACHTEN": "[BEOBACHTEN]",
}


def _wrap(text: str, prefix: str, width: int = 72) -> list[str]:
    """Bricht lange Begruendungen um, damit sie im Terminal lesbar bleiben."""
    indent = " " * len(prefix)
    wrapped = textwrap.wrap(text, width=width - len(prefix)) or [""]
    return [prefix + wrapped[0]] + [indent + line for line in wrapped[1:]]


def _bar(score: int, width: int = 20) -> str:
    filled = int(round(score / 100 * width))
    return "#" * filled + "." * (width - filled)


def _money(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:.0f}"


def _price(value: float) -> str:
    if value <= 0:
        return "-"
    if value < 0.000001:
        return f"{value:.12f}".rstrip("0")
    if value < 1:
        return f"{value:.9f}".rstrip("0")
    return f"{value:,.4f}"


def render_verdict(verdict: Verdict, verbose: bool = True) -> str:
    snap = verdict.snapshot
    lines: list[str] = []
    add = lines.append

    add("=" * 72)
    add(f"{snap.symbol}  -  {snap.name}"[:72])
    add(f"Mint:  {snap.mint}")
    if snap.url:
        add(f"Chart: {snap.url}")
    add("=" * 72)

    add(f"Bewertung  {verdict.score:3d}/100  [{_bar(verdict.score)}]  {TIER_MARK.get(verdict.tier, verdict.tier)}")
    add(f"Phase      {verdict.stage.value.upper()}")
    lines.extend(_wrap(verdict.stage.erklaerung, "           "))
    add("")

    age = snap.age_minutes
    age_text = "unbekannt" if age < 0 else (
        f"{age:.0f} Min." if age < 120 else f"{age / 60:.1f} Std."
    )
    buys, sells = snap.txns.get("h1", (0, 0))

    add("-- Marktdaten " + "-" * 58)
    add(f"  Preis            {_price(snap.price_usd)} USD")
    add(f"  Liquiditaet      {_money(snap.liquidity_usd)} USD")
    add(f"  Marktkap.        {_money(snap.market_cap)} USD"
        f"   (= {snap.mcap_to_liquidity:.1f}x Liquiditaet)"
        if snap.mcap_to_liquidity != float("inf") else
        f"  Marktkap.        {_money(snap.market_cap)} USD")
    add(f"  Alter            {age_text}")
    add(f"  Volumen 1h       {_money(snap.volume.get('h1', 0.0))} USD"
        f"   (Umschlag {snap.turnover_h1:.2f}x)")
    add(f"  Trades 1h        {buys} Kaeufe / {sells} Verkaeufe"
        f"   ({snap.buy_ratio_h1 * 100:.0f}% Kaufanteil)")
    add("  Kursaenderung    " + "  ".join(
        f"{period}: {snap.price_change.get(period, 0.0):+.1f}%"
        for period in ("m5", "h1", "h6", "h24")
    ))
    add("")

    if verdict.hard_fails:
        add("-- AUSSCHLUSSKRITERIEN " + "-" * 49)
        for item in verdict.hard_fails:
            lines.extend(_wrap(item, "  X  "))
        add("")

    if verdict.warnings:
        add("-- Warnungen " + "-" * 59)
        for item in verdict.warnings:
            lines.extend(_wrap(item, "  !  "))
        add("")

    if verbose and verdict.positives:
        add("-- Positiv " + "-" * 61)
        for item in verdict.positives:
            lines.extend(_wrap(item, "  +  "))
        add("")

    add("-- Vertragspruefung " + "-" * 53)
    if not verdict.contract_checked:
        add("  ?  Nicht durchgefuehrt (RugCheck nicht erreichbar oder ohne API-Key).")
        add("     Ohne diese Pruefung ist Mint-/Freeze-Authority und LP-Lock unbekannt.")
    for item in verdict.contract_notes:
        lines.extend(_wrap(item, "  .  "))
    add("")

    add("-- Fazit " + "-" * 63)
    if verdict.hard_fails:
        add("  Mindestens ein Ausschlusskriterium ist erfuellt. Kein Einstieg -")
        add("  unabhaengig davon, wer dir diesen Token empfohlen hat.")
    elif verdict.stage is Stage.BLOWOFF:
        add("  Die Bewegung laeuft bereits senkrecht. Ein Einstieg jetzt ist ein")
        add("  Ausstieg fuer jemand anderen. Warten oder auslassen.")
    elif verdict.tier == "BEOBACHTEN":
        add("  Keine harten Ausschlusskriterien. Das ist kein Kaufsignal, sondern")
        add("  die Erlaubnis, mit begrenztem Einsatz weiterzuschauen.")
    else:
        add("  Erhoehtes Risiko. Wenn ueberhaupt, dann mit der kleinsten")
        add("  Positionsgroesse, die du vollstaendig abschreiben kannst.")
    add("=" * 72)
    return "\n".join(lines)


def render_plan(plan: PositionPlan) -> str:
    lines: list[str] = []
    add = lines.append
    add("-- Positionsplanung " + "-" * 52)
    add(f"  Kapital gesamt       {plan.bankroll:,.2f} USD")
    add(f"  Risiko pro Trade     {plan.risk_pct:.2f}%  =  {plan.risk_usd:,.2f} USD")
    add(f"  Stop                 -{plan.stop_pct:.1f}%")
    add(f"  -> Positionsgroesse  {plan.position_usd:,.2f} USD")
    add("")
    add(f"  Preiseinfluss Kauf   {plan.entry_impact_pct:.2f}%")
    add(f"  Preiseinfluss Exit   {plan.exit_impact_pct:.2f}%  (bei 40% duennerem Pool)")
    add(f"  Gesamtkosten Umlauf  {plan.roundtrip_cost_pct:.2f}%  inkl. Gebuehren")
    if plan.stop_price is not None:
        add("")
        add(f"  Stop-Kurs            {_price(plan.stop_price)} USD")
    if plan.targets:
        for label, price, multiple in plan.targets:
            add(f"  Ziel {label:<3}             {_price(price)} USD"
                f"   (+{multiple * plan.stop_pct:.0f}%)")
    for note in plan.notes or []:
        add("")
        lines.extend(_wrap(note, "  ! "))
    return "\n".join(lines)
