"""Risikomanagement: Positionsgroesse, Preiseinfluss, Erwartungswert.

Der haeufigste Grund fuer Totalverlust ist nicht der falsche Token, sondern
die falsche Groesse. Wer 20% seines Kapitals auf einen Coin setzt, dessen
Trefferquote bei 25% liegt, ist mathematisch nach wenigen Trades bei null -
unabhaengig davon, wie gut die Auswahl war.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionPlan:
    bankroll: float
    risk_pct: float
    stop_pct: float
    position_usd: float
    risk_usd: float
    entry_impact_pct: float
    exit_impact_pct: float
    roundtrip_cost_pct: float
    liquidity_capped: bool
    stop_price: float | None = None
    targets: list[tuple[str, float, float]] | None = None
    notes: list[str] | None = None


def price_impact_pct(position_usd: float, liquidity_usd: float) -> float:
    """Preiseinfluss einer Order in einem Constant-Product-Pool (x*y=k).

    ``liquidity_usd`` ist der Gesamtwert beider Poolseiten, die relevante
    Gegenseite also etwa die Haelfte. Fuer einen Kauf ueber ``dx`` gilt
    naeherungsweise ``impact = dx / (reserve + dx)``.

    Das ist eine Naeherung ohne Gebuehren und ohne Routing ueber mehrere
    Pools - fuer die Groessenordnung reicht sie, und die Groessenordnung ist
    genau das, was die meisten Trader ignorieren.
    """
    if liquidity_usd <= 0:
        return 100.0
    reserve = liquidity_usd / 2.0
    return 100.0 * position_usd / (reserve + position_usd)


def max_position_for_impact(liquidity_usd: float, max_impact_pct: float) -> float:
    """Groesste Position, die den erlaubten Preiseinfluss noch einhaelt."""
    if liquidity_usd <= 0 or max_impact_pct <= 0:
        return 0.0
    reserve = liquidity_usd / 2.0
    fraction = max_impact_pct / 100.0
    if fraction >= 1.0:
        return float("inf")
    return reserve * fraction / (1.0 - fraction)


def plan_position(
    bankroll: float,
    liquidity_usd: float,
    entry_price: float = 0.0,
    risk_pct: float = 1.5,
    stop_pct: float = 35.0,
    max_impact_pct: float = 2.0,
    fee_pct: float = 1.0,
) -> PositionPlan:
    """Berechnet eine Positionsgroesse aus Risikobudget UND Poolgroesse.

    Zwei unabhaengige Obergrenzen, die kleinere gewinnt:
      1. Risikobudget - wie viel darf dieser Trade maximal kosten
      2. Liquiditaet  - wie viel kann der Pool ueberhaupt aufnehmen
    """
    notes: list[str] = []
    if bankroll <= 0:
        raise ValueError("Bankroll muss positiv sein")
    if not 0 < stop_pct < 100:
        raise ValueError("Stop muss zwischen 0 und 100 Prozent liegen")

    risk_usd = bankroll * risk_pct / 100.0
    by_risk = risk_usd / (stop_pct / 100.0)
    by_liquidity = max_position_for_impact(liquidity_usd, max_impact_pct)

    position = min(by_risk, by_liquidity)
    liquidity_capped = by_liquidity < by_risk
    if liquidity_capped:
        notes.append(
            f"Position durch Liquiditaet begrenzt: Risikobudget wuerde "
            f"{by_risk:,.0f} USD erlauben, der Pool vertraegt nur {by_liquidity:,.0f} USD "
            f"bei {max_impact_pct:.1f}% Preiseinfluss."
        )

    entry_impact = price_impact_pct(position, liquidity_usd)
    # Beim Ausstieg ist der Pool durch den eigenen Einstieg leicht groesser,
    # aber im Stressfall (alle verkaufen) deutlich duenner. Konservativ: 60%.
    exit_impact = price_impact_pct(position, liquidity_usd * 0.6)
    roundtrip = entry_impact + exit_impact + fee_pct

    if roundtrip > stop_pct / 2:
        notes.append(
            f"Warnung: Ein- und Ausstieg kosten zusammen {roundtrip:.1f}% - "
            f"das frisst einen erheblichen Teil des {stop_pct:.0f}%-Stops auf, "
            "bevor sich der Kurs ueberhaupt bewegt hat."
        )

    stop_price = entry_price * (1 - stop_pct / 100.0) if entry_price > 0 else None
    targets: list[tuple[str, float, float]] | None = None
    if entry_price > 0:
        # R-Vielfache: bei einer Trefferquote unter 30% braucht es 3R+ Gewinner.
        targets = [
            (f"{multiple}R", entry_price * (1 + multiple * stop_pct / 100.0), multiple)
            for multiple in (1.0, 2.0, 3.0, 5.0)
        ]

    return PositionPlan(
        bankroll=bankroll,
        risk_pct=risk_pct,
        stop_pct=stop_pct,
        position_usd=position,
        risk_usd=min(risk_usd, position * stop_pct / 100.0),
        entry_impact_pct=entry_impact,
        exit_impact_pct=exit_impact,
        roundtrip_cost_pct=roundtrip,
        liquidity_capped=liquidity_capped,
        stop_price=stop_price,
        targets=targets,
        notes=notes,
    )


def expectancy(win_rate: float, avg_win_r: float, avg_loss_r: float = 1.0) -> float:
    """Erwartungswert pro Trade in R (R = das riskierte Kapital).

    Positiv = das System traegt sich. Negativ = jeder weitere Trade kostet
    im Mittel Geld, egal wie gut sich einzelne Gewinner anfuehlen.
    """
    win_rate = max(0.0, min(1.0, win_rate))
    return win_rate * avg_win_r - (1 - win_rate) * abs(avg_loss_r)


def required_win_rate(avg_win_r: float, avg_loss_r: float = 1.0) -> float:
    """Trefferquote, ab der ein System bei gegebenem Gewinn/Verlust-Verhaeltnis traegt."""
    if avg_win_r <= 0:
        return 1.0
    return abs(avg_loss_r) / (avg_win_r + abs(avg_loss_r))


def risk_of_ruin(win_rate: float, risk_pct: float, avg_win_r: float = 2.0,
                 trades: int = 200, simulations: int = 2000, ruin_level: float = 0.5) -> float:
    """Anteil simulierter Verlaeufe, die auf ``ruin_level`` des Kapitals fallen.

    Monte-Carlo mit fixem Bruchteilseinsatz. Zeigt, was die reine
    Erwartungswert-Rechnung verschweigt: auch ein positives System ruiniert
    dich, wenn der Einsatz pro Trade zu gross ist.
    """
    import random

    ruined = 0
    fraction = risk_pct / 100.0
    for _ in range(simulations):
        equity = 1.0
        for _ in range(trades):
            if random.random() < win_rate:
                equity *= 1 + fraction * avg_win_r
            else:
                equity *= 1 - fraction
            if equity <= ruin_level:
                ruined += 1
                break
    return ruined / simulations
